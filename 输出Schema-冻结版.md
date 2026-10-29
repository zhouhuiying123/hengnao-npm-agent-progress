# 输出Schema-冻结版.md
> 本Schema为A2/B2/A1唯一对齐标准，任何修改需群内公示并全量替换
> ⚠️ 粘给AI时需去掉所有 `//` 注释，只保留纯净JSON（AI可能把注释原样输出导致A1解析报错）

```json
{
  "request_id": "demo-001",
  "package": "example-pkg",
  "version": "1.2.3",
  "mode": "offline",
  "check_status": "partial",        // 仅允许: completed/partial/input_error/conflict/system_error
  "risk_level": "unknown",          // 仅允许: high/medium/low/unknown（输入错误/对象冲突时留空；信息不足不能写low）
  "confidence": "low",              // 仅允许: high/medium/low（证据可靠程度，不表示恶意概率）
  "confidence_reason": "恶意情报资料不可用，无法完成核心检查",
  "signals": [],                    // 每条必须有可定位evidence，禁止编造
  "coverage": {
    "malware_intelligence": "unavailable",  // 仅允许: passed/flagged/unavailable/not_applicable
    "metadata": "passed",
    "provided_scripts": "not_applicable"
  },
  "unverified": ["恶意情报资料不可用"],
  "review_required": true,
  "advice": "补充可用的情报材料后重新检查",
  "policy_version": "v1.0",
  "knowledge_snapshot": "填写实际知识库快照版本"
}
```
