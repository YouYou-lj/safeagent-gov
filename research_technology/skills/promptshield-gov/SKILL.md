---
name: promptshield-gov
description: 检测进入政企智能体上下文的提示注入、越狱、知识投毒和敏感信息诱导，并输出可审计证据与处置动作。
version: 1.1.0
---

# PromptShield-Gov

## 公开入口

`src/provenance.py:analyze_text_input`

规则消融基线为 `src/detector.py:detect_input_risk`。

## 输入与输出

- 输入：`text`、来源类型、来源标识、会话、信任分数、元数据和 B0—B3 模式。
- 输出：风险类型、等级、分数、分层证据、来源决策、证据图、处置动作和延迟。

规则与分类器参数只从 `policies/` 加载。当前版本支持五类来源、规范化、长文本分段、可解释轻量分类、可选复核，以及跨来源证据图。

## 验证

在仓库根目录运行：

```bash
python -m pytest research_technology/skills/promptshield-gov/tests -q
```
