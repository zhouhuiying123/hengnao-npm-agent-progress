# A2 · node6「解析」代码草稿 V0.3（输出校验与规范化节点）

> 编制：A2 · 2026-11-11
> 适用：画布 node6（`代码` 节点），配合 2026-11-11 版 node0 提示词（14 字段输出）
> 定位变更：V0.2 是「精确匹配判定器」（吃 RAG 候选、输出命中结论）；**V0.3 改为「确定性输出校验器」**——原因见第一节
> 本地单测：12 个场景全部通过（见第五节）

---

## 一、为什么改定位（重要，先看这段）

11-11 巡检发现两件事：

1. node0 提示词已把「判定 + 报告生成」全部收进模型内部，直接输出 `report_text`，结束节点渲染的是 `{{$.node8.result_key}} {{$.node0.report_text}}`
2. **node6 的输出没有被任何节点引用**，代码仍是 146 字符空壳 → 它现在是悬空的

也就是说：原本设计里"模型整理证据、代码做确定性判定"的分工，实际变成了"模型全包"。这有明确风险——B 组零代码的失败模式（同一恶意包 4 次只中 1 次）就是模型自己判导致的，低代码侧现在把防线撤掉了。

**两条路，我建议走 A**：

- **A（本稿）**：把 node6 改成**输出校验器**——不参与风险判定（避免和 RAG 打架），只做模型做不到的事：逐字段校验 14 字段结构、枚举白名单、跨字段一致性，并确定性注入 `request_id` / `review_required` / `policy_version`。这一步把"模型输出不可控"变成"不合格输出当场被拦下"，是评分表「可控性」和「输出规范性」两项的直接得分点，改动成本最低（粘代码 + 配 2 个输入）
- **B**：把判定下沉进代码节点（V0.2 思路），让 RAG 只整理证据。结构最干净，但要重写 node0 提示词并把判定逻辑全部搬到代码里，工作量在 A1 侧，本周不一定来得及

无论走哪条，**校验层都该有**——模型输出 14 个字段、4 个枚举，靠人眼看是不现实的。

---

## 二、节点配置（A1 照此填）

**输入参数**

| 参数名 | 值（引用） | 必填 | 说明 |
|---|---|---|---|
| `rag_result` | `$.node0.result_key` | ✅ | RAG 的 14 字段输出（对象或 JSON 字符串均可） |
| `target_package` | `$.node1.package` | 可选 | 用于交叉核对：输出里的 package 必须等于它 |
| `target_version` | `$.node1.version` | 可选 | 同上 |

**输出参数**

| 参数名 | 类型 | 说明 |
|---|---|---|
| `valid` | Boolean | 结构校验是否通过（硬性指标，false 表示模型输出不合规） |
| `errors` | String | 违规项列表，JSON 数组字符串；valid=true 时为空数组 |
| `warnings` | String | 可疑但不致命的项，JSON 数组字符串 |
| `result` | String | 规范化后的完整 JSON（补了 request_id / review_required 等确定性字段），下游直接用这个 |
| `request_id` | String | 确定性生成的请求标识 |
| `review_required` | Boolean | 确定性推导的人工复核标记 |

> 结束节点建议改为渲染 `{{$.node6.result}}`（或继续用 `{{$.node0.report_text}}`，两者内容一致，前者多了校验与元信息）。

---

## 三、代码（整段粘贴，Python）

```python
# coding=utf-8
from runtime import Args
import json
import re
import random
import time

# ---------- 常量：v2 Schema ----------
REQUIRED_FIELDS = [
    "report_text", "package", "version", "retrieval_status", "risk_level",
    "confidence", "poisoning_status", "vulnerability_findings",
    "injection_suspected", "evidence", "candidate_matches",
    "false_positive_note", "unverified", "summary",
]

ENUMS = {
    "retrieval_status": ["relevant", "irrelevant", "insufficient"],
    "risk_level": ["high", "low", "unknown"],
    "confidence": ["high", "medium", "low"],
    "poisoning_status": [
        "malicious_record_matched", "benign_record_matched",
        "false_positive_record_matched", "unconfirmed",
    ],
    "candidate_label": ["malicious", "benign", "false_positive_legit"],
    "candidate_status": ["unverified", "confirmed", "recalled", "false_positive"],
    "affected_status": ["affected", "inferred_affected", "not_affected", "unknown"],
    "match_basis": ["exact_version", "explicit_range", "fixed_inference", "no_match", "unknown"],
}

POLICY_VERSION = "v1.0"
KNOWLEDGE_SNAPSHOT = "kb_v0_2_malicious_100"  # 与知识库实际版本保持一致，变更时同步改这里

# 非 high 结论下，报告文本不得出现的"安全类"表述
SAFE_PHRASES = ["安全", "无风险", "未发现任何问题", "可以放心", "不存在风险", "未发现风险"]
# 报告文本里不得泄露的内部字段名
LEAK_FIELDS = ["candidate_matches", "poisoning_status", "retrieval_status",
               "vulnerability_findings", "false_positive_note", "risk_level"]


def _get_input(args, name, default=None):
    """安全取输入：平台未配置某参数时不抛异常。"""
    try:
        return getattr(args.input, name, default)
    except Exception:
        return default


def _to_dict(raw):
    """把 RAG 输出转成 dict：支持 dict / JSON 字符串 / 带代码围栏的字符串。"""
    if raw is None:
        return None, "输入为空"
    if isinstance(raw, dict):
        return raw, None
    if isinstance(raw, (list, tuple)) and raw and isinstance(raw[0], dict):
        return raw[0], None
    if not isinstance(raw, str):
        try:
            return json.loads(json.dumps(raw)), None
        except Exception:
            return None, "输入类型无法解析：%s" % type(raw).__name__
    text = raw.strip()
    if not text:
        return None, "输入为空字符串"
    # 剥离 Markdown 代码围栏
    fence = re.match(r"^```[a-zA-Z]*\s*(.*?)\s*```$", text, re.DOTALL)
    if fence:
        text = fence.group(1).strip()
    # 只取第一个完整 JSON 对象
    start = text.find("{")
    if start < 0:
        return None, "未找到 JSON 对象"
    depth = 0
    in_str = False
    esc = False
    for i in range(start, len(text)):
        ch = text[i]
        if in_str:
            if esc:
                esc = False
            elif ch == "\\":
                esc = True
            elif ch == '"':
                in_str = False
            continue
        if ch == '"':
            in_str = True
        elif ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                candidate = text[start:i + 1]
                try:
                    return json.loads(candidate), None
                except Exception as e:
                    return None, "JSON 解析失败：%s" % str(e)[:80]
    return None, "JSON 未闭合"


def _gen_request_id():
    """确定性生成：当前时间 + 随机尾号。不由模型生成（模型会把日期写成训练数据里的旧日期）。"""
    return "req_%s_%04d" % (time.strftime("%Y%m%d_%H%M%S"), random.randint(0, 9999))


def _check_enum(obj, key, errors, path="顶层"):
    allowed = ENUMS.get(key) or []
    val = obj.get(key)
    if val not in allowed:
        errors.append("%s.%s 取值非法：%r（允许：%s）" % (path, key, val, "/".join(allowed)))
        return False
    return True


def _validate(d, target_pkg=None, target_ver=None):
    """逐字段校验，返回 (errors, warnings)。errors 非空即 valid=False。"""
    errors = []
    warnings = []

    # 1. 字段齐全
    missing = [f for f in REQUIRED_FIELDS if f not in d]
    if missing:
        errors.append("缺少必需字段：%s" % ", ".join(missing))
    extra = [k for k in d.keys() if k not in REQUIRED_FIELDS]
    if extra:
        warnings.append("存在 Schema 外字段（不影响判定，但建议清理）：%s" % ", ".join(extra))

    # 2. 类型
    for key in ["report_text", "package", "version", "summary"]:
        if key in d and not isinstance(d.get(key), str):
            errors.append("%s 必须为字符串，实际 %s" % (key, type(d.get(key)).__name__))
    if "injection_suspected" in d and not isinstance(d.get("injection_suspected"), bool):
        errors.append("injection_suspected 必须为布尔值，实际 %r" % (d.get("injection_suspected"),))
    for key in ["vulnerability_findings", "candidate_matches", "unverified"]:
        if key in d and not isinstance(d.get(key), list):
            errors.append("%s 必须为数组，实际 %s" % (key, type(d.get(key)).__name__))

    # 3. 枚举
    for key in ["retrieval_status", "risk_level", "confidence", "poisoning_status"]:
        if key in d:
            _check_enum(d, key, errors)

    # 4. 候选数组逐条校验
    cands = d.get("candidate_matches")
    if isinstance(cands, list):
        for idx, c in enumerate(cands):
            path = "candidate_matches[%d]" % idx
            if not isinstance(c, dict):
                errors.append("%s 不是对象" % path)
                continue
            if not c.get("source_id"):
                errors.append("%s.source_id 为空（禁止无来源候选）" % path)
            if not c.get("evidence"):
                errors.append("%s.evidence 为空（禁止无原文证据的候选）" % path)
            label = c.get("label")
            if label not in ENUMS["candidate_label"]:
                errors.append("%s.label 非法：%r（只接受 malicious/benign/false_positive_legit）" % (path, label))
            if c.get("status") is not None and c.get("status") not in ENUMS["candidate_status"]:
                errors.append("%s.status 非法：%r" % (path, c.get("status")))
            # 中文标签说明模型把中文写进来了
            if isinstance(label, str) and re.search(r"[\u4e00-\u9fa5]", label):
                errors.append("%s.label 含中文：%r（必须用英文枚举值）" % (path, label))

    # 5. 漏洞数组逐条校验
    finds = d.get("vulnerability_findings")
    if isinstance(finds, list):
        for idx, f in enumerate(finds):
            path = "vulnerability_findings[%d]" % idx
            if not isinstance(f, dict):
                errors.append("%s 不是对象" % path)
                continue
            if f.get("affected_status") not in ENUMS["affected_status"]:
                errors.append("%s.affected_status 非法：%r" % (path, f.get("affected_status")))
            if f.get("match_basis") not in ENUMS["match_basis"]:
                errors.append("%s.match_basis 非法：%r" % (path, f.get("match_basis")))

    # 6. 跨字段一致性
    rs = d.get("retrieval_status")
    cand_count = len(cands) if isinstance(cands, list) else 0
    find_count = len(finds) if isinstance(finds, list) else 0
    risk = d.get("risk_level")

    if rs == "relevant" and cand_count == 0 and find_count == 0:
        errors.append("retrieval_status=relevant 但候选与漏洞数组同时为空（自相矛盾）")
    if rs == "insufficient" and (cand_count > 0 or find_count > 0):
        errors.append("retrieval_status=insufficient 但存在记录（自相矛盾）")

    malicious_hit = False
    if isinstance(cands, list):
        for c in cands:
            if isinstance(c, dict) and c.get("label") == "malicious":
                malicious_hit = True
    if risk == "high" and not malicious_hit:
        errors.append("risk_level=high 但无 label=malicious 的候选记录（高风险必须有恶意记录支撑）")
    if malicious_hit and risk != "high":
        warnings.append("存在 label=malicious 记录但 risk_level=%r，需确认是否遗漏 high" % risk)

    # 7. 注入汇总一致性
    inj_top = d.get("injection_suspected")
    inj_sub = any(isinstance(c, dict) and c.get("injection_suspect") for c in (cands or []))
    if inj_sub and inj_top is not True:
        errors.append("候选含 injection_suspect=true，但顶层 injection_suspected 不为 true")

    # 8. 报告文本检查
    report = d.get("report_text")
    if isinstance(report, str):
        if len(report) < 100:
            warnings.append("report_text 仅 %d 字，低于建议的 150 字" % len(report))
        if len(report) > 500:
            warnings.append("report_text 达 %d 字，超出建议的 350 字" % len(report))
        leaked = [f for f in LEAK_FIELDS if f in report]
        if leaked:
            errors.append("report_text 泄露内部字段名：%s" % ", ".join(leaked))
        if risk != "high":
            hits = [p for p in SAFE_PHRASES if p in report]
            if hits:
                errors.append("risk_level=%r 时 report_text 含安全类表述：%s" % (risk, "/".join(hits)))

    summary = d.get("summary")
    if isinstance(summary, str) and len(summary) > 120:
        warnings.append("summary 达 %d 字，超出建议的 100 字" % len(summary))

    # 9. 包名/版本交叉核对
    if target_pkg and d.get("package") and d.get("package") != target_pkg:
        errors.append("输出 package=%r 与目标 %r 不一致（可能张冠李戴）" % (d.get("package"), target_pkg))
    if target_ver and d.get("version") and d.get("version") != target_ver:
        errors.append("输出 version=%r 与目标 %r 不一致" % (d.get("version"), target_ver))

    return errors, warnings


def _review_rule(d):
    """人工复核标记：确定性规则，不交给模型。"""
    return bool(
        d.get("risk_level") == "high"
        or d.get("injection_suspected") is True
        or d.get("retrieval_status") == "insufficient"
    )


def handler(args: Args) -> dict:
    raw = _get_input(args, "rag_result", None)
    if raw is None:
        raw = _get_input(args, "input", None)
    tgt_pkg = _get_input(args, "target_package", None)
    tgt_ver = _get_input(args, "target_version", None)

    d, err = _to_dict(raw)
    if d is None:
        return {
            "valid": False,
            "errors": json.dumps([err or "无法解析 RAG 输出"], ensure_ascii=False),
            "warnings": json.dumps([], ensure_ascii=False),
            "result": "{}",
            "request_id": _gen_request_id(),
            "review_required": True,
        }

    errors, warnings = _validate(d, tgt_pkg, tgt_ver)

    # 规范化：只补确定性字段，不覆盖模型给出的业务字段
    out = dict(d)
    out.setdefault("request_id", _gen_request_id())
    out["review_required"] = _review_rule(d)
    out.setdefault("policy_version", POLICY_VERSION)
    out.setdefault("knowledge_snapshot", KNOWLEDGE_SNAPSHOT)
    # 补齐缺失字段的空值，保证下游字段访问不报错
    defaults = {
        "report_text": "", "package": "", "version": "",
        "retrieval_status": "insufficient", "risk_level": "unknown", "confidence": "low",
        "poisoning_status": "unconfirmed", "vulnerability_findings": [],
        "injection_suspected": False, "evidence": None, "candidate_matches": [],
        "false_positive_note": None, "unverified": [], "summary": "",
    }
    for k, v in defaults.items():
        if k not in out:
            out[k] = v

    return {
        "valid": len(errors) == 0,
        "errors": json.dumps(errors, ensure_ascii=False),
        "warnings": json.dumps(warnings, ensure_ascii=False),
        "result": json.dumps(out, ensure_ascii=False),
        "request_id": out["request_id"],
        "review_required": out["review_required"],
    }
```

---

## 四、设计说明

1. **只做校验与规范化，不参与风险判定**——避免与 node0 的口径打架。所有业务字段一律照抄模型输出，不修正、不改写
2. **`request_id` 由代码生成**：`req_YYYYMMDD_HHMMSS_NNNN`。此前模型多次把日期写成 2023-10-27，这类字段绝不能交给模型
3. **`review_required` 用确定性规则推导**：`risk_level=high` 或 `injection_suspected=true` 或 `retrieval_status=insufficient` → true。这是评分表「可控性」可直接观测的指标
4. **errors 与 warnings 分级**：结构/枚举/自相矛盾类问题记 errors（valid=false，必须修）；字数、多余字段、可疑但合法的记 warnings（不阻断）
5. **八条硬性校验对应 Schema v2 第六节验收指标**：字段齐全、类型、四组枚举、候选证据非空、跨字段矛盾（relevant 但全空 / insufficient 却有记录 / high 无恶意记录）、注入汇总一致、报告文本泄露与安全表述、包名版本一致性

---

## 五、本地单测（15 项断言全过）

| # | 场景 | 期望 | 结果 |
|---|---|---|---|
| 1 | 合法输出（high + malicious 命中） | valid=true | ✅ |
| 2 | 合法输出（insufficient + 全空） | valid=true | ✅ |
| 2b | 同上，人工复核规则 | `review_required=true` | ✅ |
| 2c | 良性记录命中（low） | valid=true | ✅ |
| 2d | 同上，人工复核规则 | `review_required=false` | ✅ |
| 3 | 缺 3 个字段 | valid=false，指出缺失字段 | ✅ |
| 4 | `risk_level=medium`（v2 已取消） | valid=false，枚举非法 | ✅ |
| 5 | `risk_level=high` 但无 malicious 候选 | valid=false，指出无恶意记录支撑 | ✅ |
| 6 | `retrieval_status=relevant` 但两数组全空 | valid=false，自相矛盾 | ✅ |
| 7 | 候选 `label=恶意`（中文） | valid=false，中文标签 | ✅ |
| 8 | 候选 `source_id` 为空 | valid=false，无来源 | ✅ |
| 9 | `report_text` 出现 `candidate_matches` 字样 | valid=false，泄露字段名 | ✅ |
| 10 | unknown 但 report_text 写"未发现风险" | valid=false，安全类表述 | ✅ |
| 11 | 输入是带 ```json 围栏的字符串 | valid 正常，围栏被剥离 | ✅ |
| 12 | 输入是坏 JSON | valid=false，errors 说明解析失败 | ✅ |

补充验证：`request_id` 格式匹配 `^req_\d{8}_\d{6}_\d{4}$`；`insufficient` 场景 `review_required=true`；多余字段只进 warnings 不阻断。

---

## 六、如果走 B 路线（判定下沉）怎么办

V0.2（`A2-node6解析代码草稿-V0.2-2026-11-08.md`）里的 `_version_in_range` / `_match_candidate` 可直接复用，只需把输入从"RAG candidate_matches"换成"v2 的 candidate_matches + vulnerability_findings"，输出改为回填 `risk_level` / `poisoning_status`。但前提是 node0 提示词退回"只整理证据、不下结论"，否则两边都会改结论，反而更乱。**建议本周先上 A 路线的校验器，B 路线留到第 5 周优化轮。**
