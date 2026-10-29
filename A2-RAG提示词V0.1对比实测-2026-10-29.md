# A2 · RAG 提示词 V0 → V0.1 前后对比实测（2026-10-29）

> 本轮为一次完整的提示词优化轮次（A2-Prompt-01）：同一画布、同一知识库、同一模型参数，只改 RAG 节点系统提示词，用同一组用例复测。
> 提示词全文：《A2-RAG提示词-V0.1.md》｜V0 问题原文：《A2-RAG输出核对-2026-10-29.md》

---

## 一、操作留痕

| 项 | 内容 |
|---|---|
| 修改对象 | 画布 `RAG推理决策`（node0）**系统提示词**（唯一改动点） |
| 版本 | V0（1548 字） → V0.1（2144 字） |
| 保存方式 | 节点配置抽屉右上角对勾确认 → 画布「保存」 |
| 平台版本历史 | v1「初始」2026-10-29 13:21:00（**回退点**）→ v2「配置节点RAG推理决策」2026-10-29 14:29:02 |
| 未改动 | 模型（HengNao-r1 / temp 0.7 / max_tokens 1024 / top_k -1 / top_p 1）、知识库及检索参数（返回片段 20）、输出约束（仍为空）、用户提示词、下游节点、冻结 Schema |

---

## 二、三用例前后对比

### RAG-T01 库内真实样本 `@3stripes/shared@999.0.0`

| 维度 | V0 | V0.1 |
|---|---|---|
| 输出形态 | ```` ```json ```` 围栏包裹 | **裸 JSON** ✅ |
| retrieval_status | relevant | relevant |
| candidate_matches | 1 条 | 1 条 |
| source_id | null | null ❌ 仍缺失 |
| behavior | null | null ❌ 仍缺失 |
| source | 知识库名（有值） | null ❌ 退化 |
| status | `listed_unverified`（自造） | **`unverified`**（取 KB risk_type）✅ |
| 证据 | 含 SHA-256 | 概述性描述，无 SHA |
| summary | 客观 | 客观「缺乏行为细节和来源标识」 |

V0.1 原文：
```json
{
  "package": "@3stripes/shared",
  "version": "999.0.0",
  "retrieval_status": "relevant",
  "candidate_matches": [
    {
      "source_id": null,
      "package": "@3stripes/shared",
      "affected_versions": "999.0.0",
      "behavior": null,
      "source": null,
      "status": "unverified",
      "evidence": "npm 包 `@3stripes/shared` 的版本 `999.0.0` 已被标记为 **恶意（malicious）**。不过，该标记目前处于 **未核实（unverified）** 状态，系统给出的置信度为 **中等（medium）**。"
    }
  ],
  "unverified": ["检索记录显示该版本出现在恶意包清单中，但无具体恶意行为描述及独立核实报告"],
  "summary": "检索到与目标包名+版本完全匹配的清单记录，状态为未核实，缺乏行为细节和来源标识"
}
```

### RAG-T02 正常包 `lodash@4.17.21`（误报用例）

| 维度 | V0 | V0.1 |
|---|---|---|
| retrieval_status | relevant ❌ | **insufficient** ✅ |
| candidate_matches | 1 条**编造**情报（`npm-advisory-2021-10-22`、"Supply Chain Attack via Code Obfuscation"） | **[]** ✅ |
| status | confirmed ❌ | 无（空数组）✅ |
| summary | "状态已确认" ❌ | "知识库未检索到与 lodash 4.17.21 完全匹配的情报记录" ✅ |

**结论：正常包误报已消除。**

### RAG-T03 不存在包 `zzz-not-a-real-package-9f3k2@1.0.0`（回归用例）

| 维度 | V0 | V0.1 |
|---|---|---|
| retrieval_status | insufficient | insufficient ✅ |
| candidate_matches | [] | [] ✅ |
| 有无"该包安全"类表述 | 无 | 无 ✅ |

**结论：无回归。**

---

## 三、结论

**修复的（提示词层面，A2 成果）**
1. Markdown 围栏 → 裸 JSON，下游可直接 `json.loads`。
2. `status` 不再自造枚举，只取知识库 `risk_type`（`unverified`）。
3. 正常包不再被编造情报判为命中——这是本轮最重要的收益。

**未修复的（不属提示词，需他人配合）**
1. `source_id` / `behavior` 仍为 null。原因指向知识库分块：检索日志显示召回片段从 `RY_V0_2>>>{ "sample_id": "npm-mal-v02-018", "package_name": "@kvytech/..."` 开始，即记录被切断、`sample_id` 落在上一块。需 A3/B3 按 `<<<NPM_RECORD_BOUNDARY_V0_2>>>` 作为自定义分隔符或调整分块大小。
2. `source` 在 V0.1 中退化为 null（V0 曾填知识库名）。下轮可把「source 未知时填知识库名」写进映射规则，属可再优化项。
3. RAG 节点「输出约束」仍为空，建议 A1 启用 guided_json，以节点级 Schema 兜底。

**记法说明**：本轮是「一轮真实优化」，可计入项目要求的优化轮次；但**不能**记为完全通过——RAG 输出仍未达到「情报编号可回查」的验收标准。
