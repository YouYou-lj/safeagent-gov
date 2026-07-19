# 固定 Python 与 uv 环境

项目本地开发环境固定为 Python 3.11.12 和 uv 0.7.0：

- `.python-version` 固定 Python 补丁版本；
- `.uv-version` 固定 uv CLI 版本；
- `uv.lock` 固定跨平台依赖解析；
- `.venv/` 保存项目虚拟环境；
- `.uv-python/` 保存项目专用的 uv 管理解释器；
- `.uv-cache/` 保存项目专用下载缓存。

后三个目录均在 `.gitignore` 与 `.dockerignore` 中排除，不会进入 Git 或可选研究镜像构建上下文，也不会把依赖
安装到系统 Python。

## 首次建立或重建

先安装 `.uv-version` 指定的 uv，然后在仓库根目录运行：

```bash
./scripts/setup_uv_env.sh
```

Windows PowerShell 使用同一跨平台初始化实现：

```powershell
./scripts/setup_uv_env.ps1
```

两个包装入口都调用 `scripts/setup_uv_env.py`，校验 uv 版本、安装项目专用 Python、按 `uv.lock` 重建
`.venv`、执行依赖一致性检查并核对 Python
补丁版本。`uv sync --frozen` 不允许在安装过程中静默改写锁文件。

## 固定环境内执行命令

推荐通过包装脚本执行，避免误用系统 Python：

```bash
./scripts/uv_run.sh python -m pytest -q
./scripts/uv_run.sh python -m ruff check .
./scripts/uv_run.sh python -m mypy research_technology/mcp
./scripts/uv_run.sh uvicorn backend.main:app --reload --port 8000
```

也可以激活 `.venv`，但自动化、CI 和文档命令统一优先使用 `uv_run.sh`。

## 更新依赖

只有经过评审的依赖变更才允许更新锁文件：

```bash
UV_CACHE_DIR=.uv-cache UV_PYTHON_INSTALL_DIR=.uv-python uv lock --python 3.11.12
./scripts/setup_uv_env.sh
```

更新后必须运行完整测试与评测。`requirements.lock`、`requirements-dev.lock` 仅服务于可选研究复现；
`uv.lock` 是桌面开发和 CI 的权威锁文件，两类环境都限定在 Python 3.11。
