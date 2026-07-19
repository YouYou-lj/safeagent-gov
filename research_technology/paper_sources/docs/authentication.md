# API 身份认证与角色隔离

除 `/`、`/health` 和 OpenAPI 页面外，业务 API 使用 SafeAgent Token（HMAC-SHA256）Bearer 身份。
令牌绑定主体、租户、角色、scope、签发/过期时间、受众、签发者和随机 `jti`；最大有效期 24 小时。
请求体中的 `user_role`、`user`、`agent` 和审批 `actor` 均不参与授权，服务端始终以已验签声明覆盖。

本地签发示例：

```bash
python -m safeagent_gov.auth issue \
  --subject demo-admin \
  --tenant demo-government \
  --role admin \
  --ttl 3600
```

将输出写入前端侧边栏，或仅在当前进程环境中设置 `SAFEAGENT_API_TOKEN`。签名密钥优先来自
`SAFEAGENT_AUTH_SIGNING_SECRET`（至少 32 字节）；未配置时生成权限为 `0600` 的
`backend/data/.auth_signing_key`，该文件已被 Git 忽略。

审计链与能力票据分别使用 `SAFEAGENT_AUDIT_SIGNING_SECRET`、`SAFEAGENT_CAPABILITY_SECRET`；未配置时同样在
数据库目录生成 `.audit_signing_key` 和 `.capability_signing_key`（mode `0600`）。三类密钥不得复用，镜像构建上下文会排除这些文件。生产环境应改用 KMS/HSM 注入和轮换。

角色边界：

- `staff/manager/operator/visitor`：按四场景目录运行 Agent；角色还会继续进入 MCP RBAC。
- `reviewer/security_reviewer/manager/admin`：查看本租户待审批并记录决定，审批 actor 强制为令牌主体。
- `security_reviewer/reviewer/admin`：上传并扫描 Skill。
- `auditor/security_reviewer/admin`：运行或查看评测。
- `admin/replayer`：创建回放 bundle 和执行无副作用回放。
- 其他已认证角色只能按服务端映射读取脱敏审计视图。

所有 trace、审批和工具上下文都绑定租户。跨租户 trace 查询返回 404 以避免 ID 枚举；只有显式带有
`audit:cross_tenant` scope 的受信令牌可跨租户审计。当前 HMAC 是单部署信任域认证，生产 IAM/OIDC
接入时应替换验签后端，而不改变 `AuthClaims -> PrincipalIdentity -> GatewayContext` 契约。

认证成功后还按 `tenant_id:subject` 进入进程内滑动窗口限流，默认每 60 秒 120 次，可通过
`SAFEAGENT_API_RATE_LIMIT` 与 `SAFEAGENT_API_RATE_WINDOW_SECONDS` 收紧。超过门槛返回 429；多副本部署应把
同一接口替换为 Redis/API Gateway 限流器。
