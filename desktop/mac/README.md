# macOS 构建与发布

仓库将开发验证和对外发布分成两条链路。普通 CI 使用 ad-hoc 签名验证包结构、启动和 sidecar 生命周期；受保护的 Release 工作流才使用 Developer ID 和 Apple 公证凭据。

## 🧰 开发构建

在 macOS 原生环境运行：

```bash
cd desktop
bash mac/build-mac.sh
```

该脚本构建当前 CPU 架构的 PyInstaller sidecar、Tauri App 和 DMG，并执行 sidecar 健康检查、App 启动、应用退出后的进程回收、签名结构检查和 DMG 校验。可通过 `SAFEAGENT_MAC_RECLAIM_TIMEOUT_SECONDS` 调整较慢 runner 的回收观察窗口，CI 使用 30 秒。

双架构 GitHub 工作流分别使用 `macos-14` 的 Apple Silicon runner 和 `macos-15-intel` 的 Intel runner，产物名明确包含 `aarch64` 或 `x86_64`。[^1]

## 🔐 正式签名与公证

正式发布由 `.github/workflows/release-macos.yml` 调用：

```bash
cd desktop
bash mac/build-release.sh
```

脚本拒绝缺少 Apple 凭据的执行，并要求 Tauri 完成 Developer ID 签名和公证，随后验证 App 签名、DMG Stapling 与 Gatekeeper。Tauri 的 macOS 分发文档说明，直接下载分发需要代码签名，面向 macOS 10.14.5 及更高版本还需要公证。[^2]

以下 Secrets 只配置在受保护的 `macos-release` Environment：

- `APPLE_CERTIFICATE`
- `APPLE_CERTIFICATE_PASSWORD`
- `APPLE_SIGNING_IDENTITY`
- `APPLE_API_ISSUER`
- `APPLE_API_KEY`
- `APPLE_API_PRIVATE_KEY`
- `KEYCHAIN_PASSWORD`

`entitlements.plist` 和发布脚本只描述发布边界，不包含证书、私钥或口令。开发环境的 ad-hoc 签名不能表述为正式发布签名；在真实 Apple 凭据演练通过前，也不能宣称公证已经验证。

## 🧭 维护约束

- macOS 专用配置、图标、entitlements、签名、公证和 DMG 实现保留在 `desktop/mac/`。
- 通用 Rust/Tauri 逻辑和 sidecar 协议保留在 `desktop/src-tauri/`。
- 发布产物名称必须包含版本和 CPU 架构。
- 新增 entitlement 前记录必要性，并检查最终 App 与 DMG。

[^1]: [GitHub Docs：标准 GitHub-hosted runner](https://docs.github.com/en/actions/reference/runners/github-hosted-runners#standard-github-hosted-runners-for-public-repositories)
[^2]: [Tauri：macOS Code Signing](https://v2.tauri.app/distribute/sign/macos/)
