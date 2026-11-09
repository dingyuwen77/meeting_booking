"""腾讯 ADP 可接入的 Streamable HTTP MCP Server。

真实写操作默认关闭。最终成员身份仅从可信网关签名的 HTTP Header 取得。
本模块依赖官方 mcp Python SDK v2；不得让模型通过 JSON 提供 userId。
"""

import asyncio
import os
from contextlib import asynccontextmanager
from functools import lru_cache
from typing import Any

from mcp.server.mcpserver import Context, MCPServer

from .bizvideo import BizVideoProvider
from .contract import get_inline_schema
from .identity import verify_identity
from .service import MeetingService
from .settings import Settings
from .state import StateStore


@asynccontextmanager
async def _lifespan(server: MCPServer):
    """服务退出时释放惰性创建的 Provider 连接，不让 ping 依赖业务配置。"""
    try:
        yield
    finally:
        if _service.cache_info().currsize:
            _service().provider.close()
            _service.cache_clear()


class MeetingMCPServer(MCPServer):
    """在 SDK 公共工具发现入口投影正式 Schema，业务校验仍由原入口执行。"""

    async def list_tools(self) -> list[Any]:
        """为三项业务工具提供可独立解析的入参和结果契约。"""
        tools = await super().list_tools()
        kinds = {
            "submit_meeting_request": "request",
            "continue_meeting_request": "continue",
            "get_meeting_operation": "operation-query",
        }
        for tool in tools:
            if tool.name in kinds:
                tool.input_schema = {
                    "type": "object", "required": ["request"],
                    "additionalProperties": False,
                    "properties": {"request": get_inline_schema(kinds[tool.name])},
                }
                tool.output_schema = get_inline_schema("result")
        return tools


mcp = MeetingMCPServer("meeting-booking", version="0.2.0", lifespan=_lifespan)


@lru_cache(maxsize=1)
def _service() -> MeetingService:
    """在事件循环首次业务调用时创建并复用服务依赖。"""
    settings = Settings.from_env()
    return MeetingService(
        settings,
        StateStore(settings.db_path),
        BizVideoProvider(settings),
    )


def _actor(ctx: Context):
    """从本次 HTTP 请求头提取并验证可信成员身份。"""
    svc = _service()
    return verify_identity(ctx.headers or {}, svc.settings)


@mcp.tool()
def ping_meeting_server() -> dict[str, Any]:
    """只读握手探针：不访问会畅，也不暴露凭据或用户信息。"""
    return {"ok": True, "service": "meeting-booking", "protocol": "meeting.v1"}


@mcp.tool()
async def whoami_probe(ctx: Context) -> dict[str, Any]:
    """验证企微用户身份是否经可信网关动态签名；不接受模型指定用户。"""
    actor = _actor(ctx)
    return {"corp_id": actor.corp_id, "user_id": actor.user_id}


@mcp.tool()
async def submit_meeting_request(
    request: dict[str, Any], ctx: Context,
) -> dict[str, Any]:
    """提交 meeting.request.v1，支持 CREATE、UPDATE、CHECK。"""
    actor = _actor(ctx)
    return await asyncio.to_thread(_service().submit, actor, request)


@mcp.tool()
async def continue_meeting_request(
    request: dict[str, Any], ctx: Context,
) -> dict[str, Any]:
    """继续 meeting.continue.v1：补参数、选择会议或取消待处理申请。"""
    actor = _actor(ctx)
    return await asyncio.to_thread(_service().continue_request, actor, request)


@mcp.tool()
async def get_meeting_operation(
    request: dict[str, Any], ctx: Context,
) -> dict[str, Any]:
    """只读查询 operation_id 的已存状态；不重新执行会畅写操作。"""
    actor = _actor(ctx)
    return await asyncio.to_thread(_service().get_operation, actor, request)


def main() -> None:
    """按环境监听配置启动 Streamable HTTP MCP 服务。"""
    host = os.getenv("MEETING_MCP_HOST", "127.0.0.1")
    port = int(os.getenv("MEETING_MCP_PORT", "4561"))
    mcp.run(
        transport="streamable-http",
        host=host,
        port=port,
        stateless_http=True,
        json_response=True,
    )


if __name__ == "__main__":
    main()
