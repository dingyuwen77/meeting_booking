"""临时身份参数传递 POC；静态调用密钥不能证明员工身份。"""

import hmac
from typing import Any

from mcp.server.mcpserver import Context, MCPServer
from mcp.server.mcpserver.exceptions import ToolError
from mcp.types import ToolAnnotations

from .identity import is_valid_user_id
from .settings import IdentityProbeSettings


def register_identity_probe(server: MCPServer) -> None:
    """启动时按独立配置注册探针；关闭时不留下可直接调用的入口。"""
    settings = IdentityProbeSettings.from_env()
    if not settings.enabled:
        return

    @server.tool(annotations=ToolAnnotations(
        read_only_hint=True, destructive_hint=False, idempotent_hint=True, open_world_hint=False,
    ))
    async def identity_binding_probe(actor_user_id: str, ctx: Context) -> dict[str, Any]:
        """临时回显收到的 UserID，仅验证参数传递，不认证员工、不执行会议业务。"""
        headers = {key.lower(): value for key, value in (ctx.headers or {}).items()}
        supplied = headers.get("x-meeting-identity-probe-key", "")
        # 只比较请求 Header，不把工具参数当凭据；字节比较也能安全拒绝非 ASCII 输入。
        if not hmac.compare_digest(supplied.encode("utf-8"), settings.key.encode("utf-8")):
            raise ToolError("身份参数探针调用认证失败")
        if not is_valid_user_id(actor_user_id):
            raise ToolError("用户标识格式不正确")
        return {
            "success": True,
            "mcp_client_authenticated": True,
            "received_user_id": actor_user_id,
            "probe_only": True,
        }
