# 仓库治理规范

## 评审可发现性

- 根目录 `PROJECT_MAP.md` 是唯一总导航。
- `innovations/` 只说明创新主张、算法、基线、消融、结果和源码链接，不复制实现。
- `skills/` 保存可独立加载的安全 Skill；`mcp/` 保存网关与 Server；应用代码不得混入两者。
- 每个一级目录必须有 README，说明职责、公开接口、运行命令、测试命令和依赖边界。

## Skill 目录契约

```text
skills/<skill-name>/
├── SKILL.md
├── manifest.yaml
├── README.md
├── src/
├── policies/
├── tests/
├── examples/
└── benchmarks/
```

Skill 必须能独立导入和测试；策略不得散落在页面或 API 路由中。

## MCP 目录契约

```text
mcp/
├── gateway/
├── servers/<server-name>/
│   ├── manifest.yaml
│   └── server.py
├── adapters/
├── policies/
├── schemas/
├── tests/
└── examples/
```

每个 Server 必须声明能力、最小权限、模拟/沙箱方式和失败关闭行为。共享请求/响应 Schema 与契约测试放在顶层 `schemas/` 和 `tests/`；Server 复杂到需要私有 Schema 或专属攻击集时，再在对应目录内增设 `schemas/`、`tests/`、`examples/`。

## 创新目录契约

```text
innovations/Ix_name/
├── README.md       # 一句话创新与适用边界
├── hypothesis.md   # 可证伪假设
├── algorithm.md    # 算法/机制
├── baselines.md    # 对比方法
├── ablations.yaml  # 消融开关
└── evidence.md     # 源码、测试、数据、结果链接
```

## 代码与版本规则

- `main` 始终可运行；使用 `feat/*`、`fix/*`、`refactor/*`、`exp/*` 分支。
- Conventional Commits；一次提交只做一个可验证变更。
- 公共 Schema、Skill API、MCP 协议使用 SemVer；破坏性变更必须有迁移说明。
- Python 代码统一 formatter、lint、type check；新增核心逻辑必须有测试。
- 大数据/模型使用 DVC 或 Git LFS；仓库保存 manifest、来源、许可证和哈希。
- 结果文件必须记录 commit、配置、模型/策略/数据版本、随机种子和环境。
- CI 门禁：格式、lint、类型、unit、contract、integration、安全扫描、benchmark smoke。
- 禁止提交密钥、个人数据、真实政务数据、缓存、虚拟环境和不可追溯生成物。

## 迁移原则

1. 先建立新目录和公开接口。
2. 移动唯一实现，旧路径只做代理导入。
3. 运行原有与新增测试。
4. 更新 `PROJECT_MAP.md` 和依赖关系。
5. 一个迭代后删除代理，禁止长期维护双份代码。
