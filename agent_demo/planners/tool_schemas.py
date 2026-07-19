"""Strict schemas for untrusted planner-produced tool arguments."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from safeagent_gov.errors import PlanningError


class _ToolArgs(BaseModel):
    model_config = ConfigDict(extra="forbid")


class FileReadArgs(_ToolArgs):
    path: str = Field(min_length=1, max_length=2048)


class FileWriteArgs(_ToolArgs):
    path: str = Field(min_length=1, max_length=2048)
    content: str = Field(default="", max_length=100_000)


class FileDeleteArgs(_ToolArgs):
    path: str = Field(min_length=1, max_length=2048)


class SendEmailArgs(_ToolArgs):
    to: str = Field(min_length=3, max_length=320)
    subject: str = Field(default="", max_length=500)
    content: str = Field(default="", max_length=100_000)
    attachments: list[str] = Field(default_factory=list, max_length=10)


class BrowserVisitArgs(_ToolArgs):
    url: str = Field(min_length=1, max_length=4096)


class ApiCallArgs(_ToolArgs):
    url: str = Field(min_length=1, max_length=4096)
    method: Literal["GET", "POST", "PUT", "PATCH", "DELETE"] = "GET"
    body: dict[str, Any] | None = None


class ShellExecArgs(_ToolArgs):
    command: str = Field(min_length=1, max_length=10_000)


class DatabaseArgs(_ToolArgs):
    sql: str = Field(min_length=1, max_length=100_000)


TOOL_ARGUMENT_MODELS: dict[str, type[_ToolArgs]] = {
    "file_read": FileReadArgs,
    "file_write": FileWriteArgs,
    "file_delete": FileDeleteArgs,
    "send_email": SendEmailArgs,
    "browser_visit": BrowserVisitArgs,
    "api_call": ApiCallArgs,
    "shell_exec": ShellExecArgs,
    "db_query": DatabaseArgs,
    "db_write": DatabaseArgs,
}


def _bounded_json(value: Any, *, depth: int = 0, counter: list[int] | None = None) -> None:
    if counter is None:
        counter = [0]
    counter[0] += 1
    if counter[0] > 500:
        raise PlanningError("规划参数节点数超过 500")
    if depth > 8:
        raise PlanningError("规划参数嵌套深度超过 8")
    if value is None or isinstance(value, (bool, int, float)):
        return
    if isinstance(value, str):
        if len(value) > 100_000:
            raise PlanningError("规划参数字符串过长")
        return
    if isinstance(value, list):
        if len(value) > 100:
            raise PlanningError("规划参数数组过长")
        for item in value:
            _bounded_json(item, depth=depth + 1, counter=counter)
        return
    if isinstance(value, dict):
        if len(value) > 100:
            raise PlanningError("规划参数对象字段过多")
        for key, item in value.items():
            if not isinstance(key, str) or len(key) > 160:
                raise PlanningError("规划参数键无效")
            _bounded_json(item, depth=depth + 1, counter=counter)
        return
    raise PlanningError(f"规划参数包含非 JSON 类型: {type(value).__name__}")


def validate_tool_args(tool_name: str, tool_args: dict[str, Any]) -> dict[str, Any]:
    model = TOOL_ARGUMENT_MODELS.get(tool_name)
    if model is None:
        raise PlanningError(f"规划器提出未注册工具: {tool_name}")
    _bounded_json(tool_args)
    try:
        return model.model_validate(tool_args).model_dump(mode="python", exclude_none=True)
    except Exception as exc:
        raise PlanningError(f"工具 {tool_name} 参数不符合 Schema") from exc


def tool_schema_catalog() -> dict[str, Any]:
    return {
        name: model.model_json_schema()
        for name, model in sorted(TOOL_ARGUMENT_MODELS.items())
    }
