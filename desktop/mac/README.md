# macOS 构建

支持 macOS 13+ 的 Apple Silicon 和 Intel 原生构建。当前仓库已在 Apple Silicon 验证 `.app`、Sidecar、
ad-hoc 签名和进程回收；`.dmg` 由本目录脚本生成。面向他人分发仍需 Developer ID、Apple 公证与 Stapling。

```bash
cd desktop
bash mac/build-mac.sh
```

`entitlements.plist`、`notarize.sh` 是发布边界说明，不包含证书或口令。正式签名和公证只在受保护的
Release runner 执行，开发环境的 ad-hoc 签名不能表述为正式发布签名。
