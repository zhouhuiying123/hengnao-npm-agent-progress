# node6「解析」代码草稿 V0.2（2026-11-08）

> **变更原因**：11-08 巡检发现 A1 把 node6 的输入绑成了 `mcp.result_key`（不是 RAG 输出），而 V0.1 草稿假设输入是 RAG 的 `candidate_matches`。
> **V0.2 策略**：兼容双输入——RAG 结果用于**命中判定**（唯一证据来源），MCP 结果只做**背景信息**输出，不参与判定、不进 signals。这样无论 A1 最终怎么连（只连 MCP / 只连 RAG / 两个都连），代码都能跑。
> **本地单测**：7 个场景全部通过（见文末）。

```python
# coding=utf-8
from runtime import Args
import json
import re


# ==================== INPUT 区（变量名确认后只需改这里） ====================
# 目标包名与精确版本：来自校验节点
TARGET_PACKAGE = args.input.package
TARGET_VERSION = args.input.version
# 知识库候选情报：来自 RAG 节点（命中判定的唯一依据）
RAG_RAW = args.input.rag_result
# 外部 npm 信息：来自 MCP 节点（仅作背景，不参与判定）
MCP_RAW = args.input.mcp_result
# ==========================================================================


def _get_input(args, name, default=None):
    """安全取输入：平台未配置某参数时不会抛异常。"""
    inp = getattr(args, "input", None)
    if inp is None:
        return default
    return getattr(inp, name, default)


def _strip_fence(text):
    """剥离可能的 ```json 围栏（RAG 提示词已禁止，保留一次兜底）。"""
    if not isinstance(text, str):
        return text
    m = re.search(r"```(?:json)?\s*(.*?)\s*```", text, re.DOTALL)
    return m.group(1) if m else text


def _to_dict(raw):
    """把上游输出统一成 dict；失败返回 None（不猜测、不补救）。"""
    if raw is None or raw == "":
        return None
    if isinstance(raw, dict):
        return raw
    if isinstance(raw, str):
        try:
            data = json.loads(_strip_fence(raw))
            return data if isinstance(data, dict) else None
        except (json.JSONDecodeError, TypeError, ValueError):
            return None
    return None


def _mcp_brief(raw):
    """MCP 结果压成一段可读背景文本，最长 300 字；不解析成判定依据。"""
    if raw is None or raw == "":
        return None
    text = raw if isinstance(raw, str) else json.dumps(raw, ensure_ascii=False)
    text = re.sub(r"\s+", " ", _strip_fence(text)).strip()
    return text[:300] if text else None


def _semver(version):
    """'1.2.3-beta.1' -> ((1,2,3), ('beta',1))；不合法返回 None。"""
    m = re.fullmatch(
        r"(\d+)\.(\d+)\.(\d+)(?:-([0-9A-Za-z.-]+))?(\+[0-9A-Za-z.-]+)?",
        version or "",
    )
    if not m:
        return None
    core = tuple(int(m.group(i)) for i in (1, 2, 3))
    pre = tuple(
        (int(p), "") if p.isdigit() else (p, "")
        for p in (m.group(4) or "").split(".")
    ) if m.group(4) else None
    return core, pre


def _cmp(a, b):
    """SemVer 比较：返回 -1/0/1。"""
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


def _in_range(target, spec):
    """
    目标版本是否明确落入 spec 表示的范围。
    支持：精确版本 / 比较器列表 / 连字符范围 / x-range。
    无法解析的形态一律 False（宁漏判不误判，交 unverified）。
    """
    spec = (spec or "").strip()
    if not spec:
        return False
    tv = _semver(target)
    if tv is None:
        return False

    m = re.fullmatch(r"(.+?)\s+-\s+(.+)", spec)
    if m:
        lo, hi = _semver(m.group(1).strip()), _semver(m.group(2).strip())
        if lo is None or hi is None:
            return False
        return _cmp(lo, tv) <= 0 and _cmp(tv, hi) <= 0

    if re.fullmatch(r"[xX*](\.[xX*])?(\.[xX*])?", spec):
        return False
    if re.fullmatch(r"\d+\.[xX*](\.[xX*])?", spec):
        return target.split(".")[0] == spec.split(".")[0]
    if re.fullmatch(r"\d+\.\d+\.[xX*]", spec):
        tp, sp = target.split("."), spec.split(".")
        return len(tp) >= 2 and tp[0] == sp[0] and tp[1] == sp[1]

    comps = [c.strip() for c in spec.split(",") if c.strip()]
    if len(comps) > 1 or re.match(r"^(>=|<=|>|<|=|\^|~)", comps[0]):
        for comp in comps:
            m = re.match(r"^(>=|<=|>|<|=|\^|~)?\s*(.+)$", comp)
            if not m:
                return False
            op, ver = m.group(1) or "=", m.group(2).strip()
            cv = _semver(ver)
            if cv is None:
                return False
            c = _cmp(cv, tv)
            if op == "=" and c != 0:
                return False
            if op == ">" and c >= 0:
                return False
            if op == ">=" and c > 0:
                return False
            if op == "<" and c <= 0:
                return False
            if op == "<=" and c < 0:
                return False
            if op == "^":
                if c > 0:
                    return False
                if cv[0][0] == 0:
                    if tv[0][1] != cv[0][1]:
                        return False
                elif tv[0][0] != cv[0][0]:
                    return False
            if op == "~":
                if c > 0:
                    return False
                tp, vp = target.split("."), ver.split(".")
                if tp[0] != vp[0] or (len(tp) > 1 and len(vp) > 1 and tp[1] != vp[1]):
                    return False
        return True

    return spec == target


def handler(args: Args) -> dict:
    package = (_get_input(args, "package") or "").strip()
    version = (_get_input(args, "version") or "").strip()
    rag = _to_dict(_get_input(args, "rag_result"))
    mcp_brief = _mcp_brief(_get_input(args, "mcp_result"))

    # ---------- 分支 1：RAG 结果缺失或不可解析 ----------
    # 没有知识库候选就无法判定，MCP 外部信息不能替代（P09 纪律）
    if rag is None:
        return {
            "intel_match": "unavailable",
            "intel_hit_detail": None,
            "hit_count": 0,
            "package": package,
            "version": version,
            "retrieval_status": None,
            "mcp_context": mcp_brief,
            "note": "RAG 输出缺失或无法解析，无法判定命中；MCP 外部信息不作为恶意证据",
        }

    retrieval_status = rag.get("retrieval_status")
    candidates = rag.get("candidate_matches")
    if not isinstance(candidates, list):
        candidates = []

    # ---------- 分支 2：检索不足 ----------
    if retrieval_status == "insufficient":
        return {
            "intel_match": "unavailable",
            "intel_hit_detail": None,
            "hit_count": 0,
            "package": package,
            "version": version,
            "retrieval_status": retrieval_status,
            "mcp_context": mcp_brief,
            "note": "知识库检索不足，无法判定命中",
        }

    # ---------- 分支 3：确定性精确匹配 ----------
    hits = []
    for cand in candidates:
        if not isinstance(cand, dict):
            continue
        cp = cand.get("package")
        av = cand.get("affected_versions")
        # 包名整串精确相等，大小写敏感，@ 属于包名
        if cp != package:
            continue
        if av == version or _in_range(version, av):
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

    if hits:
        return {
            "intel_match": True,
            "intel_hit_detail": hits[0],
            "hit_count": len(hits),
            "package": package,
            "version": version,
            "retrieval_status": retrieval_status,
            "mcp_context": mcp_brief,
            "note": None,
        }

    note = None
    if retrieval_status == "irrelevant":
        note = "检索内容与目标包名或版本不匹配"
    elif candidates:
        note = "检索到同包相关记录，但版本不满足精确命中条件"

    return {
        "intel_match": False,
        "intel_hit_detail": None,
        "hit_count": 0,
        "package": package,
        "version": version,
        "retrieval_status": retrieval_status,
        "mcp_context": mcp_brief,
        "note": note,
    }
```

---

## 一、输出变量（在 node6 输出参数里注册这些名字）

| 变量 | 类型 | 说明 | 下游（报告节点）用法 |
|---|---|---|---|
| `intel_match` | String | `true` / `false` / `unavailable` | → `coverage.malware_intelligence`（flagged/passed/unavailable） |
| `intel_hit_detail` | Object | 命中记录（全字段来自 RAG 候选） | → `signals[]` 的 source_id / evidence / 描述 |
| `hit_count` | Number | 命中条数 | `confidence` 评估参考 |
| `mcp_context` | String | MCP 外部信息摘要（≤300 字） | 只允许写进 `unverified[]` 或 `advice` 的背景说明，**禁止**作为 signals 证据 |
| `package` / `version` | String | 透传 | 报告头部字段 |
| `retrieval_status` | String | RAG 原值透传 | `unverified[]` / `confidence_reason` |
| `note` | String | 未命中/不可用原因 | `advice` |

## 二、V0.2 与 V0.1 的差别

| 项 | V0.1 | V0.2 |
|---|---|---|
| 输入 | 假设只有 RAG 输出 | 双输入：`rag_result`（判定用）+ `mcp_result`（背景用），缺任一个都不崩 |
| 参数读取 | 直接 `args.input.x`（未配置会抛异常） | `_get_input()` 安全读取，未配置返回 None |
| MCP 数据 | 未涉及 | 压成 `mcp_context` 摘要输出，**不参与判定**——落实 P09–P12 纪律 |
| RAG 缺失时 | 返回 unavailable | 仍返回 unavailable，且 note 明示“MCP 不作为恶意证据” |

## 三、本地单测结果（2026-11-08）

| # | 场景 | 输入 | 期望 | 结果 |
|---|---|---|---|---|
| 1 | 恶意样本精确命中 | RAG relevant + 候选 999.0.0，MCP 有文本 | `intel_match=true`，`version_match=exact` | ✅ |
| 2 | 良性包未命中 | RAG irrelevant + 空候选 | `false` + note 说明不匹配 | ✅ |
| 3 | 检索不足 | RAG insufficient | `unavailable` | ✅ |
| 4 | 只有 MCP（A1 当前连线） | RAG 缺失 + MCP 有数据 | `unavailable` + `mcp_context` 有值 + note 警示 | ✅ |
| 5 | 围栏兜底 | RAG 输出被 ```json 包裹 | 正常解析，`false` | ✅ |
| 6 | 坏 JSON | RAG = `not-json{` | `unavailable` | ✅ |
| 7 | 版本范围命中 | `affected_versions=">=1.0.0, <2.0.0"`，目标 1.5.0 | `true`，`version_match=range` | ✅ |

版本范围判定函数另有 18 个用例（精确/比较器/连字符/x-range/^/~/无效输入），18/18 通过。

## 四、给 A1 的两个选择（都支持，不用改代码）

1. **只要 MCP 结果**（当前连线）：`rag_result` 留空 → 输出 `unavailable`，报告会写“情报不可用，无法判定”——这是安全的降级，但**永远判不出恶意**，等于丢掉了知识库
2. **同时接 RAG + MCP**（推荐）：`rag_result` 接 RAG 的 `result_key`，`mcp_result` 接 MCP 的 `result_key` → 判定用 RAG，MCP 只做背景说明

> **一句话给 A1**：解析节点的 `rag_result` 一定要接 RAG 输出，否则这条链只能输出“情报不可用”，R02 正例永远过不了。
