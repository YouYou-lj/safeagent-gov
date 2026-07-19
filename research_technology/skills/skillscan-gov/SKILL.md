---
name: skillscan-gov
description: 在不执行目标代码的前提下扫描 Skill、插件和压缩包中的供应链风险，并给出行为与权限证据。
version: 1.1.0
---

# SkillScan-Gov

## 公开入口

`src/scanner.py:scan_skill_package`

## 安全边界

- 禁止导入或执行待扫描代码。
- ZIP/目录输入限制路径、符号链接、压缩比、加密成员、嵌套压缩、文件数、单文件和总大小。
- 网络访问和 Shell 执行默认关闭。

当前主路径使用 Python AST 与 JavaScript/TypeScript 结构化语法树，联合跨文件调用/数据流、manifest 权限、SBOM 和固定依赖风险快照。原 token 扫描保留为 B1 消融，不参与 B3 主裁决。

## 验证

```bash
python -m pytest research_technology/skills/skillscan-gov/tests -q
python research_technology/benchmarks/runners/eval_skillscan.py
```
