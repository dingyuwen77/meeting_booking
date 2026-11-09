"""腾讯 ADP 可接入的 Streamable HTTP MCP Server。

真实写操作默认关闭。最终成员身份仅从可信网关签名的 HTTP Header 取得。
本模块依赖官方 mcp Python SDK v2；不得让模型通过 JSON 提供 userId。
"""

import asyncio
import os
from functools import lru_cache
from typing import Any

from mcp.server.mcpserver import Context, MCPServer

from .bizvideo import BizVideoProvider
from .identity import verify_identity
from .service import MeetingService
from .settings import Settings
from .state import StateStore

mcp = MCPServer("meeting-booking", version="0.2.0")


@lru_cache(maxsize=1)
def _service() -> MeetingService:
    settings = Settings.from_env()
    return MeetingService(
        settings,
        StateStore(settings.db_path),
        BizVideoProvider(settings),
    )


def _actor(ctx: Context):
    svc = _service()
    return verify_identity(ctx.headers or {}, svc.settings)


@mcp.tool()
def ping_meeting_server() -> dict[str, Any]:
    """只读握手探针：不访问会畅，也不暴露凭据或用户信息。"""
    return {"ok": True, "service": "meeting-booking", "protocol": "meeting.v1"}


@mcp.tool()
def whoami_probe(ctx: Context) -> dict[str, Any]:
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
