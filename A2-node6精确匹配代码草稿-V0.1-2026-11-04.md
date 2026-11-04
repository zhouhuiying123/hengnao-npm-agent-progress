# node6 精确匹配代码节点 · 草稿 V0.1（2026-11-04）

> **用途**：粘贴进画布新增的 `代码_7C9B8G`（node6），承担 RAG 提示词 V0.1 边界条款承诺的"最终命中判定交由后续 Code 节点"。
> **设计原则**：与校验节点同一风格（try/except + 确定性判定 + 不编造）；命中判定只用**整串精确相等**（大小写敏感、作用域符属于包名），版本范围仅在目标版本明确落入时判命中——与低代码侧 P07/P08 用例判定口径一致。
> **⚠️ 待 A1 确认的 3 个变量名**（确认后只需改代码头部 INPUT 区 3 行）：
> 1. RAG 节点输出的变量名（草稿假设 `args.input.rag_result`，若实际是 `result` / `node0.result_key` 请对应替换）
> 2. 校验节点输出的包名字段（草稿假设 `args.input.package`）
> 3. 校验节点输出的版本字段（草稿假设 `args.input.version`）

```python
# coding=utf-8
from runtime import Args
import json
import re

# ============ INPUT 区（A1 确认变量名后只需改这里） ============
# RAG 节点输出（JSON 字符串或对象，结构见 RAG 提示词 V0.1 输出格式）
RAG_RAW = args.input.rag_result
# 校验节点输出的目标包名与精确版本
TARGET_PACKAGE = args.input.package
TARGET_VERSION = args.input.version
# =============================================================


def _strip_code_fence(text):
    """兜底：剥离可能的 ```json 围栏（RAG 提示词已禁止，但保留一次剥离）。"""
    if not isinstance(text, str):
        return text
    m = re.search(r"```(?:json)?\s*(.*?)\s*```", text, re.DOTALL)
    return m.group(1) if m else text


def _parse_rag(raw):
    """解析 RAG 输出；失败返回 None（不猜测、不补救）。"""
    try:
        data = json.loads(raw) if isinstance(raw, str) else raw
        return data if isinstance(data, dict) else None
    except (json.JSONDecodeError, TypeError, ValueError):
        return None


def _semver_tuple(version):
    """'1.2.3-beta.1' -> ((1,2,3), ('beta',1))；不合法返回 None。"""
    m = re.fullmatch(
        r"(\d+)\.(\d+)\.(\d+)(?:-([0-9A-Za-z.-]+))?(\+[0-9A-Za-z.-]+)?",
        version,
    )
    if not m:
        return None
    core = tuple(int(m.group(i)) for i in (1, 2, 3))
    pre = tuple(
        (int(p), "") if p.isdigit() else (p, "")
        for p in (m.group(4) or "").split(".")
    ) if m.group(4) else None
    return core, pre


def _cmp_semver(a, b):
    """返回 -1/0/1；含预发布号者小于同版本无预发布号（SemVer 规范）。"""
    ca, pa = a
    cb, pb = b
    if ca != cb:
        return -1 if ca < cb else 1
    if pa is None and pb is None:
        return 0
    if pa is None:
        return 1
    if pb is None:
        return -1
    return -1 if pa < pb else (1 if pa > pb else 0)


def _version_in_range(target, spec):
    """
    判定目标版本是否明确落入 affected_versions 表示的范围。
    支持四种形态（与知识库 v0.2 实际数据对齐）：
      1. 精确版本：'1.2.3'
      2. 比较器列表（逗号分隔）：'>=1.0.0, <2.0.0'
      3. 连字符范围：'1.0.0 - 1.9.9'
      4. 通配 x-range：'1.2.x' / '1.x'
    无法解析的形态一律返回 False（宁漏判不误判，由 unverified 记录）。
    """
    spec = (spec or "").strip()
    if not spec:
        return False

    tv = _semver_tuple(target)
    if tv is None:
        return False

    # 形态 3：连字符范围
    m = re.fullmatch(r"(.+?)\s+-\s+(.+)", spec)
    if m:
        lo, hi = _semver_tuple(m.group(1).strip()), _semver_tuple(m.group(2).strip())
        if lo is None or hi is None:
            return False
        return _cmp_semver(lo, tv) <= 0 and _cmp_semver(tv, hi) <= 0

    # 形态 4：x-range（x/X/* 作通配，仅匹配到对应段）
    if re.fullmatch(r"[xX*](\.[xX*])?(\.[xX*])?", spec):
        return False  # 全通配等于"任意版本"，命中判定不明确，交 unverified
    if re.fullmatch(r"\d+\.[xX*](\.[xX*])?", spec):
        parts = target.split(".")
        return parts[0] == spec.split(".")[0]
    if re.fullmatch(r"\d+\.\d+\.[xX*]", spec):
        parts = target.split(".")
        sp = spec.split(".")
        return len(parts) >= 2 and parts[0] == sp[0] and parts[1] == sp[1]

    # 形态 2：比较器列表
    comparators = [c.strip() for c in spec.split(",") if c.strip()]
    if len(comparators) > 1 or re.match(r"^(>=|<=|>|<|=|\^|~)", comparators[0]):
        for comp in comparators:
            m = re.match(r"^(>=|<=|>|<|=|\^|~)?\s*(.+)$", comp)
            if not m:
                return False
            op, ver = m.group(1) or "=", m.group(2).strip()
            cv = _semver_tuple(ver)
            if cv is None:
                return False
            c = _cmp_semver(cv, tv)  # c<0 基准<目标；c=0 相等；c>0 基准>目标
            if op == "=" and c != 0:
                return False
            if op == ">" and c >= 0:      # 要求 目标 > 基准
                return False
            if op == ">=" and c > 0:      # 要求 目标 >= 基准
                return False
            if op == "<" and c <= 0:      # 要求 目标 < 基准
                return False
            if op == "<=" and c < 0:      # 要求 目标 <= 基准
                return False
            if op == "^":  # 同主版本且 >= 基准；基准主版本为 0 时锁定次版本
                if c > 0:
                    return False
                if cv[0][0] == 0:
                    if tv[0][1] != cv[0][1]:
                        return False
                elif tv[0][0] != cv[0][0]:
                    return False
            if op == "~":  # 锁定前两位
                if c > 0:
                    return False
                tp, vp = target.split("."), ver.split(".")
                if tp[0] != vp[0] or (len(tp) > 1 and len(vp) > 1 and tp[1] != vp[1]):
                    return False
        return True

    # 形态 1：精确版本整串相等（大小写敏感）
    return spec == target


def handler(args: Args) -> dict:
    rag = _parse_rag(_strip_code_fence(RAG_RAW))

    # ---- 分支 1：RAG 输出不可解析 → unavailable（不编造任何情报） ----
    if rag is None:
        return {
            "intel_match": "unavailable",
            "intel_hit_detail": None,
            "package": TARGET_PACKAGE,
            "version": TARGET_VERSION,
            "retrieval_status": None,
            "note": "RAG 输出无法解析为 JSON 对象",
        }

    retrieval_status = rag.get("retrieval_status")
    candidates = rag.get("candidate_matches")
    if not isinstance(candidates, list):
        candidates = []

    package = (TARGET_PACKAGE or "").strip()
    version = (TARGET_VERSION or "").strip()

    # ---- 分支 2：检索状态不足 → unavailable ----
    if retrieval_status == "insufficient":
        return {
            "intel_match": "unavailable",
            "intel_hit_detail": None,
            "package": package,
            "version": version,
            "retrieval_status": retrieval_status,
            "note": "知识库检索不足，无法判定命中",
        }

    # ---- 分支 3：确定性精确匹配（唯一允许判 true/false 的路径） ----
    hits = []
    for cand in candidates:
        if not isinstance(cand, dict):
            continue
        cp = cand.get("package")
        av = cand.get("affected_versions")
        # 包名：整串精确相等，大小写敏感，作用域符号 @ 属于包名一部分
        if cp != package:
            continue
        # 版本：精确相等，或目标版本明确落入 affected_versions 范围
        if av == version or _version_in_range(version, av):
            hits.append({
                "source_id": cand.get("source_id"),
                "package": cp,
                "affected_versions": av,
                "version_match": "exact" if av == version else "range",
                "behavior": cand.get("behavior"),
                "source": cand.get("source"),
                "status": cand.get("status"),
                "evidence": cand.get("evidence"),
            })

    # 命中：取第一条，全部字段逐字来自 candidate，不做任何补充
    if hits:
        return {
            "intel_match": True,
            "intel_hit_detail": hits[0],
            "hit_count": len(hits),
            "package": package,
            "version": version,
            "retrieval_status": retrieval_status,
        }

    # 未命中：检索有结果但无匹配记录（含 irrelevant）→ false
    # retrieval_status == relevant 且 candidate_matches 非空却全部被丢弃
    # 也归入 false，但把丢弃原因写进 note 供报告节点引用
    note = None
    if retrieval_status == "irrelevant":
        note = "检索内容与目标包名或版本不匹配"
    elif candidates:
        note = "检索到同包相关记录，但版本不满足精确命中条件"

    return {
        "intel_match": False,
        "intel_hit_detail": None,
        "package": package,
        "version": version,
        "retrieval_status": retrieval_status,
        "note": note,
    }
```

---

## 设计说明（给 A1 的对接要点）

### 输出变量（建议在 node6 输出参数里注册这几个名字）

| 变量 | 类型 | 取值 | 下游用途 |
|---|---|---|---|
| `intel_match` | string/bool | `true` / `false` / `"unavailable"` | 报告节点判定 `coverage.malware_intelligence`：true→flagged，false→passed，unavailable→unavailable |
| `intel_hit_detail` | object/null | 命中记录（字段全部来自 RAG candidate，无编造） | 报告节点 `signals[]` 的证据来源：`source_id`→报告 source_id、`evidence`→信号 evidence、`behavior`→描述 |
| `hit_count` | number | 命中条数 | 可选，报告 `confidence` 评估参考 |
| `package` / `version` | string | 透传 | 报告节点直接引用 |
| `retrieval_status` | string | 透传 RAG 原值 | 报告节点 `unverified[]` / `confidence_reason` |
| `note` | string/null | 未命中/不可用原因 | 报告节点 `advice` 参考 |

### 与冻结 Schema 的衔接

- `intel_match=true` → `coverage.malware_intelligence="flagged"`、`review_required=true`
- `intel_match=false` → `"passed"`（注意：知识库未命中≠安全，报告提示词已有兜底条款）
- `intel_match="unavailable"` → `"unavailable"`、`risk_level` 不得写 low

### 三条对齐口径（与 RAG 提示词 V0.1、P07/P08 一致）

1. 包名整串精确相等、大小写敏感、`@` 属于包名——不做近似/前缀/大小写归一化
2. 版本范围仅在目标版本**明确落入**时判命中（代码支持比较器/连字符/x-range；解析不了的形态一律不命中并交 `note`，宁漏判不误判）
3. 所有输出字段逐字来自 RAG candidate 或填 null/None——代码层不存在编造路径

### 已知边界（供评审）

- `^0.x` 与 `~` 的锁定规则按 SemVer 语义实现，若知识库实际不用这些符号可简化
- 全通配 `x`/`*`/`X` 判定不明确，直接不命中并应进 `unverified`（报告侧兜底）
- 多条命中时取第一条（`hit_count` 保留总数），如需全部可在分支 3 返回 `hits` 列表
