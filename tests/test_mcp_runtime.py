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

PROBE_KEY = "test-only-identity-probe-key-1234567890"


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


@pytest.mark.parametrize("probe_enabled", [False, True])
def test_http_mcp_identity_booking_retry_and_shutdown(tmp_path, monkeypatch, probe_enabled):
    """真实 MCP→身份→Schema→业务→SQLite→HTTP Adapter 链可查询且不重复写。"""
    cfg = settings(tmp_path)
    monkeypatch.setenv("MEETING_IDENTITY_PROBE_ENABLED", str(probe_enabled).lower())
    monkeypatch.setenv("MEETING_IDENTITY_PROBE_KEY", PROBE_KEY)
    server = mcp_server.create_server()
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
        app = server.streamable_http_app(
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
            } | ({"identity_binding_probe"} if probe_enabled else set())
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
            for name, arguments in [
                ("whoami_probe", {}),
                ("submit_meeting_request", {"request": request("op_probe_denied_001")}),
                ("continue_meeting_request", {"request": {}}),
                ("get_meeting_operation", {"request": {}}),
            ]:
                denied = rpc(client, "tools/call", {"name": name, "arguments": arguments},
                             headers={"X-Meeting-Identity-Probe-Key": PROBE_KEY})
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


@pytest.mark.parametrize("enabled", [False, True])
def test_identity_probe_settings_default_and_opt_in(monkeypatch, enabled):
    """探针配置独立读取，开关关闭时不要求密钥或业务配置。"""
    from meeting_reservation.settings import IdentityProbeSettings

    monkeypatch.delenv("MEETING_IDENTITY_PROBE_ENABLED", raising=False)
    monkeypatch.delenv("MEETING_IDENTITY_PROBE_KEY", raising=False)
    monkeypatch.setenv("MEETING_DEFAULT_PARTIES", "invalid-business-config")
    assert IdentityProbeSettings.from_env().enabled is False
    monkeypatch.setenv("MEETING_IDENTITY_PROBE_ENABLED", str(enabled).upper())
    monkeypatch.setenv("MEETING_IDENTITY_PROBE_KEY", PROBE_KEY)
    cfg = IdentityProbeSettings.from_env()
    assert cfg.enabled is enabled
    assert PROBE_KEY not in repr(cfg)


@pytest.mark.parametrize("key", ["", "short", " " * 32, "x" * 32 + "\n", "密" * 32])
def test_identity_probe_rejects_unsafe_configuration(monkeypatch, key):
    """开启时缺失或不适合 HTTP Header 的弱密钥必须阻止服务启动。"""
    monkeypatch.setenv("MEETING_IDENTITY_PROBE_ENABLED", "true")
    monkeypatch.setenv("MEETING_IDENTITY_PROBE_KEY", key)
    with pytest.raises(ValueError, match="MEETING_IDENTITY_PROBE_KEY") as error:
        mcp_server.create_server()
    assert key == "" or key not in str(error.value)


@pytest.fixture
def probe_client(tmp_path, monkeypatch):
    """使用真实 MCP HTTP 入口，任何业务初始化、SQLite 或外网访问都判失败。"""
    attempted = []

    def forbidden(*args, **kwargs):
        """记录禁止的副作用，即使 SDK 捕获异常也不能掩盖访问。"""
        attempted.append(True)
        raise AssertionError("身份参数探针触发了业务依赖")

    monkeypatch.setenv("MEETING_IDENTITY_PROBE_ENABLED", "true")
    monkeypatch.setenv("MEETING_IDENTITY_PROBE_KEY", PROBE_KEY)
    monkeypatch.setenv("MEETING_DEFAULT_PARTIES", "invalid-business-config")
    monkeypatch.setenv("MEETING_DB_PATH", str(tmp_path / "probe.sqlite3"))
    monkeypatch.setattr(mcp_server.Settings, "from_env", forbidden)
    monkeypatch.setattr(mcp_server, "StateStore", forbidden)
    monkeypatch.setattr(mcp_server, "BizVideoProvider", forbidden)
    monkeypatch.setattr(mcp_server, "MeetingService", forbidden)
    monkeypatch.setattr("sqlite3.connect", forbidden)
    monkeypatch.setattr(httpx.HTTPTransport, "handle_request", forbidden)
    mcp_server._service.cache_clear()
    app = mcp_server.create_server().streamable_http_app(
        host="127.0.0.1", json_response=True, stateless_http=True,
    )
    with TestClient(app, base_url="http://127.0.0.1:4561") as client:
        yield client
    assert attempted == []
    assert mcp_server._service.cache_info().currsize == 0
    assert not (tmp_path / "probe.sqlite3").exists()


def test_identity_probe_http_roundtrip_and_request_auth(probe_client, caplog):
    """两名成员及边界 UserID 原样回显，每次调用重新验证专用 Header。"""
    tools = rpc(probe_client, "tools/list")["tools"]
    tool = next(tool for tool in tools if tool["name"] == "identity_binding_probe")
    assert set(tool["inputSchema"]["properties"]) == {"actor_user_id"}
    assert tool["inputSchema"]["required"] == ["actor_user_id"]
    assert tool["annotations"]["readOnlyHint"] is True
    for user_id in ["EMPLOYEE_A", "EMPLOYEE_B", "a", "X" * 128, "Ab_1@.-"]:
        call = {"name": "identity_binding_probe", "arguments": {"actor_user_id": user_id}}
        result = rpc(probe_client, "tools/call", call,
                     headers={"x-meeting-identity-probe-key": PROBE_KEY})
        assert not result.get("isError", False)
        assert result["structuredContent"] == {
            "success": True, "mcp_client_authenticated": True,
            "received_user_id": user_id, "probe_only": True,
        }
    for headers in [{}, {"X-Meeting-Identity-Probe-Key": "wrong-key-do-not-echo"},
                    {"X-Meeting-Identity-Probe-Key": ""}]:
        result = rpc(probe_client, "tools/call", call, headers=headers)
        assert result["isError"] is True
        assert "received_user_id" not in str(result)
        assert "wrong-key-do-not-echo" not in str(result)
    assert PROBE_KEY not in str(tools) + caplog.text
    assert "wrong-key-do-not-echo" not in caplog.text


@pytest.mark.parametrize("arguments", [
    {}, {"actor_user_id": ""}, {"actor_user_id": " "}, {"actor_user_id": " user"},
    {"actor_user_id": "user\n"}, {"actor_user_id": "用户"}, {"actor_user_id": "a/b"},
    {"actor_user_id": "a" * 129}, {"actor_user_id": 123}, {"actor_user_id": None},
])
def test_identity_probe_rejects_invalid_user_id(probe_client, arguments):
    """缺参、错误类型、长度与非法字符不能被归一化为合法 UserID。"""
    result = rpc(probe_client, "tools/call", {
        "name": "identity_binding_probe", "arguments": arguments,
    }, headers={"X-Meeting-Identity-Probe-Key": PROBE_KEY})
    assert result["isError"] is True
    assert "received_user_id" not in str(result)


def test_identity_probe_disabled_cannot_be_called(monkeypatch):
    """默认关闭时，已知工具名也不能绕过工具发现直接调用。"""
    monkeypatch.delenv("MEETING_IDENTITY_PROBE_ENABLED", raising=False)
    monkeypatch.setenv("MEETING_IDENTITY_PROBE_KEY", "ignored-when-disabled")
    app = mcp_server.create_server().streamable_http_app(
        host="127.0.0.1", json_response=True, stateless_http=True,
    )
    with TestClient(app, base_url="http://127.0.0.1:4561") as client:
        assert "identity_binding_probe" not in {
            tool["name"] for tool in rpc(client, "tools/list")["tools"]
        }
        result = rpc(client, "tools/call", {
            "name": "identity_binding_probe", "arguments": {"actor_user_id": "EMPLOYEE_A"},
        }, headers={"X-Meeting-Identity-Probe-Key": PROBE_KEY})
        assert result["isError"] is True
