# Linux 构建

支持 x64/arm64 原生构建，产物为 AppImage 与 deb。构建机需安装 WebKitGTK 4.1、AppIndicator、Rsvg、
libxdo、OpenSSL、patchelf 和常规编译工具；Ubuntu runner 的依赖由 `build-linux.yml` 固定。

```bash
cd desktop
bash linux/build-linux.sh
```

桌面 App 与现有 Docker Compose 服务模式并存：前者使用本地 loopback Sidecar，后者继续用于服务器或多进程
部署，两者共享 Python/FastAPI 安全核心。
