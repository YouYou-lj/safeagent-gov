# Windows 构建

支持 Windows 10/11 x64 原生构建，产物为 WiX MSI 与 NSIS 安装程序。要求 Node.js、项目固定 uv/Python、
Rust MSVC 工具链、Visual Studio Build Tools 和 WebView2 构建环境。

```powershell
cd desktop
powershell -ExecutionPolicy Bypass -File windows/build-windows.ps1
```

PyInstaller 在 Windows runner 生成带 `.exe` 的 Tauri Sidecar；安装包嵌入 WebView2 离线安装器，适合受限网络。
若 Defender 对未签名开发包给出信誉提示，
必须通过固定依赖、SBOM、恶意软件扫描和 Authenticode 正式签名解决，不得指导用户关闭 Defender。
