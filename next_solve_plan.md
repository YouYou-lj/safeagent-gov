# SafeAgent-Gov 后续解决计划与执行记录

_执行日期：2026-07-20；起始基线：`main@f1d097d`_

## 📋 执行结论

- 实际测试数据集不上传到公开 GitHub 仓库；公共 CI 继续运行单元测试、机制测试和合成测试。
- macOS sidecar 增加 Tauri 父进程监视与主动退出，并补充可配置窗口、zombie 识别、进程状态和超时诊断。
- macOS 普通 CI 已扩展为 Apple Silicon 与 Intel 双架构原生构建，产物名称包含架构。
- 受保护的 macOS Release 工作流已经建立，正式签名、公证和 Stapling 只读取 GitHub Secrets。
- GitHub Actions 官方依赖已升级，Linux、Windows、macOS 和 Release 工作流使用当前有效版本。
- 定时 CI 的 Redis/Dramatiq 恢复门禁已修复，并通过真实容器强杀与 AOF 重启测试。
- 正式 Apple 公证的实际验收仍需要仓库外的 Apple Developer ID 与 App Store Connect 凭据。

## ✅ 已执行项目

| 工作项 | 实现 | 本地证据 | 状态 |
| --- | --- | --- | --- |
| macOS sidecar 生命周期 | 监视 Tauri 父 PID、可配置回收时限、zombie 判定、PID/PPID/状态诊断 | App、DMG、sidecar 启停和 1.3 秒回收通过 | 已完成 |
| macOS 双架构 CI | `macos-14` 构建 `aarch64`，`macos-15-intel` 构建 `x86_64` | 两架构 App、DMG、启动、回收与产物上传通过 | 已完成 |
| macOS 正式发布链 | 独立受保护工作流导入证书与 API Key，执行签名、公证、Stapling 和 Gatekeeper 检查 | 脚本语法和秘密边界测试通过 | 待 Apple 凭据验收 |
| Actions 升级 | checkout v6、setup-node v6、setup-uv v8.3.2、artifact v7/v8 | 技术质量和三平台云端工作流通过 | 已完成 |
| 定时恢复门禁 | 内部 compose 调用显式指定配置，探针使用可导入模块路径 | Worker 强杀恢复、审计完整性和 AOF 持久化通过 | 已完成 |
| 数据集边界 | 真实样本和结果目录保持忽略 | `git ls-files` 无数据集文件 | 已完成 |

## 💾 测试数据集决策

### 最终决策

不上传实际测试数据集到当前公开仓库。以下内容继续保持忽略：

- `research_technology/datasets/`
- `research_technology/benchmarks/datasets/`
- `research_technology/benchmarks/results/`
- `research_technology/benchmarks/failures/`

允许提交数据读取器、评测 runner、schema、无真实样本的格式说明，以及经过人工确认且没有隐私和许可风险的少量合成 fixture。不提交真实样本、攻击载荷、用户内容、密钥、无再分发许可的第三方数据或可反推样本的完整日志。

真实数据评测应在本机受控路径或私有定时 CI 中执行，只对外发布脱敏聚合指标。Release 的质量门槛应同时要求公共 CI 和私有真实数据评测通过。

## 🍎 macOS 后续开发意见

### 近期必须完成

1. 在本次变更分支上运行 Apple Silicon 和 Intel 两个 GitHub runner，确认 sidecar、App、DMG、启动和退出回收均通过。
2. 由仓库管理员在受保护的 `macos-release` Environment 配置 Apple 凭据，再执行一次非发布演练。
3. 正式发布前确认 Developer ID 签名、公证、Stapling 和 Gatekeeper 检查全部通过；没有该证据时不得宣称“可公开分发”。
4. 产物名称持续包含版本与 CPU 架构，避免 Intel 和 Apple Silicon 安装包混淆。

### 后续增强

1. 覆盖端口占用、重复启动、异常退出、系统关机信号和 sidecar 崩溃恢复。
2. 在 macOS 13、当前稳定版本及下一稳定版本测试安装、启动、升级和卸载。
3. 每次增加 entitlement 前记录必要性，并审计最终 App 与 DMG 的权限和签名。
4. 统一构建阶段耗时与校验摘要，在不破坏 DMG 产物的前提下减少重复打包。

### 平台边界

| 位置 | 应包含内容 | 不应包含内容 |
| --- | --- | --- |
| `desktop/src-tauri/` | 公共 Rust/Tauri 逻辑、通用配置、sidecar 协议 | 仅 macOS 使用的签名、公证和 DMG 脚本 |
| `desktop/mac/` | macOS 配置、图标、entitlements、签名、公证、DMG 和生命周期测试 | Windows/Linux 安装逻辑 |
| `frontend-vue/` | 三个平台共用的界面和状态管理 | 直接调用 macOS 命令的页面逻辑 |
| `safeagent_gov/`、`backend/` | 公共安全能力、API 和业务逻辑 | 只为单个桌面系统成立的路径假设 |

## 🧪 验收记录

- Python：255 passed、1 skipped，覆盖率 85.97%；跳过项仅为本地未提供的 Router 数据集。
- macOS：本机 `.app`、`.dmg`、ad-hoc 签名、健康检查、启动和 sidecar 回收通过。
- Redis/Dramatiq：真实 Worker `SIGKILL` 后恢复成功，`delivery_count=2`、`recovered_count=1`、审计完整、AOF 重启后状态保留、危险动作执行数为 0。
- 前端：lint、typecheck 和 Vitest 通过。
- 工程质量：Ruff、Mypy、Markdown 链接、仓库索引、平台边界和技术清单检查通过。
- GitHub：`technical-quality` 的 push、PR 与手动 Docker 门禁均通过；Linux、Windows、Apple Silicon 和 Intel 构建均通过。

## 🚦剩余验收

- [x] GitHub `technical-quality`、`build-macos`、`build-linux`、`build-windows` 在本次代码提交上全部通过。
- [x] Apple Silicon 与 Intel 云端产物分别完成构建、启动和 sidecar 回收验证。
- [ ] 配置真实 Apple Secrets 后完成一次正式签名与公证演练。
- [x] 应用退出后 sidecar 在规定窗口内结束，失败时输出完整诊断。
- [x] `git ls-files research_technology/benchmarks/datasets` 输出为空。
- [x] 公共测试在没有真实数据集时通过。
- [x] 平台专用代码未泄漏到共享业务目录。

## 🔐 正式发布所需 Secrets

这些值只应配置在受保护的 GitHub `macos-release` Environment，不得提交到仓库：

- `APPLE_CERTIFICATE`
- `APPLE_CERTIFICATE_PASSWORD`
- `APPLE_SIGNING_IDENTITY`
- `APPLE_API_ISSUER`
- `APPLE_API_KEY`
- `APPLE_API_PRIVATE_KEY`
- `KEYCHAIN_PASSWORD`

## 🔗 相关文件

- [macOS 构建说明](desktop/mac/README.md)
- [macOS 开发构建入口](desktop/mac/build-mac.sh)
- [macOS 正式发布入口](desktop/mac/build-release.sh)
- [macOS 生命周期验证](desktop/mac/scripts/verify_app.py)
- [技术质量工作流](.github/workflows/ci.yml)
- [macOS 双架构工作流](.github/workflows/build-macos.yml)
- [macOS 签名发布工作流](.github/workflows/release-macos.yml)
- [桌面发布工作流](.github/workflows/release.yml)
