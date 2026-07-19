"""FastAPI application entry point for GovSafeAgent."""

from __future__ import annotations

import os
from contextlib import asynccontextmanager
from urllib.parse import urlsplit

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from starlette.middleware.trustedhost import TrustedHostMiddleware

from backend.api import (
    agent_api,
    audit_api,
    auth_api,
    eval_api,
    graphify_api,
    mcp_api,
    model_api,
    policy_api,
    risk_api,
    router_api,
    skill_api,
    skill_runtime_api,
    task_api,
    tool_api,
)
from backend.database import init_db


@asynccontextmanager
async def lifespan(_: FastAPI):
    init_db()
    graphify_api.DEFAULT_GRAPHIFY_SERVICE.bootstrap_if_empty()
    skill_runtime_api.DEFAULT_SKILL_REGISTRY.load()
    model_api.DEFAULT_MODEL_REGISTRY.load()
    model_api.DEFAULT_MODEL_GATEWAY.refresh()
    await task_api.DEFAULT_TASK_DISPATCHER.start()
    try:
        yield
    finally:
        await task_api.DEFAULT_TASK_DISPATCHER.stop(drain=True)


app = FastAPI(
    title="GovSafeAgent API",
    version="0.2.0",
    description="面向政企场景的大模型智能体轻量化安全治理平台",
    lifespan=lifespan,
)


def _configured_origins() -> list[str]:
    configured = os.getenv(
        "SAFEAGENT_CORS_ORIGINS",
        "http://localhost:8501,http://127.0.0.1:8501,http://localhost:5173,http://127.0.0.1:5173",
    )
    origins = [item.strip().rstrip("/") for item in configured.split(",") if item.strip()]
    for origin in origins:
        parsed = urlsplit(origin)
        is_web_origin = parsed.scheme in {"http", "https"} and bool(parsed.netloc) and not parsed.path
        is_tauri_origin = parsed.scheme == "tauri" and parsed.netloc == "localhost" and not parsed.path
        if origin == "*" or not (is_web_origin or is_tauri_origin):
            raise RuntimeError(f"不安全或无效的 CORS 来源配置: {origin}")
    if not origins:
        raise RuntimeError("SAFEAGENT_CORS_ORIGINS 不能为空")
    return origins


def _trusted_hosts() -> list[str]:
    configured = os.getenv("SAFEAGENT_TRUSTED_HOSTS", "localhost,127.0.0.1,testserver,backend")
    hosts = [item.strip() for item in configured.split(",") if item.strip()]
    if not hosts or "*" in hosts or any("/" in item or "://" in item for item in hosts):
        raise RuntimeError("SAFEAGENT_TRUSTED_HOSTS 必须是非通配的主机名列表")
    return hosts


app.add_middleware(TrustedHostMiddleware, allowed_hosts=_trusted_hosts())
app.add_middleware(
    CORSMiddleware,
    allow_origins=_configured_origins(),
    allow_credentials=True,
    allow_methods=["GET", "POST", "OPTIONS"],
    allow_headers=["Authorization", "Content-Type"],
)


@app.middleware("http")
async def security_headers(request, call_next):
    response = await call_next(request)
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["Referrer-Policy"] = "no-referrer"
    response.headers["Permissions-Policy"] = "camera=(), microphone=(), geolocation=()"
    response.headers["Cache-Control"] = "no-store"
    return response

for router in (
    auth_api.router,
    policy_api.router,
    risk_api.router,
    tool_api.router,
    mcp_api.router,
    skill_api.router,
    audit_api.router,
    eval_api.router,
    graphify_api.router,
    router_api.router,
    skill_runtime_api.router,
    model_api.router,
    task_api.router,
    agent_api.router,
):
    app.include_router(router)


@app.get("/health", tags=["System"])
def health():
    return {"status": "ok", "service": "GovSafeAgent", "version": app.version}


@app.get("/", tags=["System"])
def root():
    return {"name": app.title, "docs": "/docs", "health": "/health"}
