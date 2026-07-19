# 技术冻结产物

- `sbom.cdx.json`：CycloneDX 1.6 格式的运行时与验证依赖清单。
- `technical_manifest.json`：基础镜像、依赖锁、离线/外部模型状态、策略版本、数据集版本、源码树和评测结果摘要。

两份 JSON 均由 `python scripts/generate_technical_manifest.py` 确定性生成，不写入当前时间；相同源码与输入会得到完全相同的内容。外部 LLM/Dify 只有在提供真实租户配置并完成联调后才能从“需配置、未声明实测”改为“已验证”。
