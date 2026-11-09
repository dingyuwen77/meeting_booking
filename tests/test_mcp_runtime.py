"""通过真实 SDK 的 HTTP 协议入口验证接线，隔离会畅外网。"""

import time
from urllib.parse import parse_qs

import httpx
import pytest
from jsonschema import Draft202012Validator, ValidationError
from starlette.testclient import TestClient
from test_booking_service import ACTOR, OTHER, request, settings

from meeting_reservation import mcp_server
from meeting_reservation.bizvideo import BizVideoProvider
from meeting_reservation.identity import sign_identity


def rpc(client, method, params=None, *, headers=None):
    """用标准 JSON-RPC 消息调用真实 Streamable HTTP ASGI 入口。"""
    response = client.post("/mcp", json={
        "jsonrpc": "2.0", "id": 1, "method": method, "params": params or {},
    }, headers={
        "Accept": "application/json, text/event-stream",
        "MCP-Protocol-Version": "2025-06-18",
        **(headers or {}),
    })
    assert response.status_code == 200, response.text
    payload = response.json()
    assert "error" not in payload, payload
    return payload["result"]


def test_http_mcp_identity_booking_retry_and_shutdown(tmp_path, monkeypatch):
    """真实 MCP→身份→Schema→业务→SQLite→HTTP Adapter 链可查询且不重复写。"""
    cfg = settings(tmp_path)
    meetings = {}
    writes = []

    def provider_http(req):
        """仅替换供应商网络响应，协议路由和业务实现均使用生产代码。"""
        fields = parse_qs(req.content.decode()) if req.method == "POST" else {
            key: [value] for key, value in req.url.params.items()
        }
        assert fields["userId"] == [ACTOR.user_id]
        endpoint = req.url.path.rsplit("/", 1)[1]
        if endpoint == "getScheduledConfListByUserId":
            data = {"confInfo": list(meetings.values())}
        elif endpoint == "getAvailableRoomsBySiteSign":
            data = [{"parties": 25, "count_available": 1}]
        elif endpoint == "confReservation":
            writes.append(fields)
            meetings["6001"] = {
                "confId": 6001, "confNumber": "8806001", "userId": ACTOR.user_id,
                "confName": fields["confName"][0], "startTime": fields["startTime"][0],
                "duration": int(fields["duration"][0]), "joinUrl": "https://example.invalid/j/6001",
            }
            data = {"confId": 6001}
        elif endpoint == "getConfDetailByConfId":
            data = meetings[fields["confId"][0]]
        else:
            raise AssertionError(endpoint)
        return httpx.Response(200, json={"status": 100, "data": data, "totalPage": 1})

    with httpx.Client(transport=httpx.MockTransport(provider_http)) as provider_client:
        provider = BizVideoProvider(cfg, provider_client)
        monkeypatch.setattr(mcp_server.Settings, "from_env", lambda: cfg)
        monkeypatch.setattr(mcp_server, "BizVideoProvider", lambda settings: provider)
        mcp_server._service.cache_clear()
        app = mcp_server.mcp.streamable_http_app(
            host="127.0.0.1", json_response=True, stateless_http=True,
        )
        with TestClient(app, base_url="http://127.0.0.1:4561") as client:
            hello = rpc(client, "initialize", {
                "protocolVersion": "2025-06-18", "capabilities": {},
                "clientInfo": {"name": "booking-regression", "version": "1"},
            })
            assert hello["serverInfo"]["name"] == "meeting-booking"
            tools = rpc(client, "tools/list")["tools"]
            assert {tool["name"] for tool in tools} == {
                "ping_meeting_server", "whoami_probe", "submit_meeting_request",
                "continue_meeting_request", "get_meeting_operation",
            }
            submit_schema = next(
                tool for tool in tools if tool["name"] == "submit_meeting_request"
            )
            validator = Draft202012Validator(submit_schema["inputSchema"])
            validator.validate({"request": request("op_schema_valid_0001")})
            with pytest.raises(ValidationError):
                validator.validate({"request": {}})
            assert "status" in submit_schema["outputSchema"]["required"]
            ping = rpc(client, "tools/call", {"name": "ping_meeting_server"})
            assert ping["structuredContent"]["ok"] is True
            denied = rpc(client, "tools/call", {"name": "whoami_probe"})
            assert denied["isError"] is True
            headers = sign_identity(ACTOR, cfg.identity_secret, int(time.time()))
            who = rpc(client, "tools/call", {"name": "whoami_probe"}, headers=headers)
            assert who["structuredContent"]["user_id"] == ACTOR.user_id
            data = request("op_mcp_runtime_0001")
            call = {"name": "submit_meeting_request", "arguments": {"request": data}}
            first = rpc(client, "tools/call", call, headers=headers)["structuredContent"]
            assert first["status"] == "COMMITTED"
            assert rpc(client, "tools/call", call, headers=headers)["structuredContent"] == first
            query = {"name": "get_meeting_operation", "arguments": {"request": {
                "schema_version": "meeting.operation-query.v1",
                "operation_id": data["operation_id"],
            }}}
            assert rpc(client, "tools/call", query, headers=headers)["structuredContent"] == first
            other = sign_identity(OTHER, cfg.identity_secret, int(time.time()))
            assert rpc(client, "tools/call", query, headers=other)["structuredContent"][
                "status"
            ] == "DENIED"
            assert len(writes) == 1
            partial = request("op_mcp_partial_0001", incomplete=True)
            pending = rpc(client, "tools/call", {
                "name": "submit_meeting_request", "arguments": {"request": partial},
            }, headers=headers)["structuredContent"]
            assert pending["status"] == "NEED_INPUT"
            cancelled = rpc(client, "tools/call", {
                "name": "continue_meeting_request", "arguments": {"request": {
                    "schema_version": "meeting.continue.v1",
                    "operation_id": "op_mcp_cancel_00001",
                    "pending_request_id": pending["pending_request_id"],
                    "expected_revision": pending["pending_revision"],
                    "decision": {"kind": "CANCEL"},
                }},
            }, headers=headers)["structuredContent"]
            assert cancelled["status"] == "CANCELLED"
            assert len(writes) == 1
        assert mcp_server._service.cache_info().currsize == 0
