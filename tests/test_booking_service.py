"""独立 Fake Provider 业务回归：不能冒充真实会畅/ADP 联调。"""

import hashlib
from datetime import datetime, timedelta, timezone
from urllib.parse import parse_qs

import httpx
import pytest

from meeting_reservation.bizvideo import (
    BizVideoProvider,
    ProviderError,
    ProviderUnknown,
    utc_form_time,
)
from meeting_reservation.identity import (
    Actor,
    IdentityError,
    sign_identity,
    verify_identity,
)
from meeting_reservation.service import MeetingService
from meeting_reservation.settings import Settings
from meeting_reservation.state import StateStore

ACTOR = Actor("corp_example", "YNND", "测试员工")
OTHER = Actor("corp_example", "OTHER", "另一位员工")


def settings(tmp_path, *, enabled=True):
    return Settings(
        site_sign="site_test",
        api_key="api_test",
        corp_id="corp_example",
        identity_secret="0123456789abcdef" * 3,
        db_path=str(tmp_path / "meeting.sqlite3"),
        default_parties=25,
        write_enabled=enabled,
        base_url="https://apinext.bizvideo.cn/openapi/v1",
        timeout_seconds=2,
    )


def datetime_future(hours=72):
    return datetime.now(timezone.utc).replace(microsecond=0) + timedelta(hours=hours)


def intent(action="CREATE", *, incomplete=False, room=None):
    start = datetime_future()
    return {
        "schema_version": "meeting.intent.v1",
        "action": action,
        "target": None,
        "meeting": {
            "title": None if action == "CHECK" else "产品评审会",
            "start_at": start.isoformat(),
            "end_at": None if incomplete else (start + timedelta(hours=1)).isoformat(),
            "timezone": "Asia/Shanghai",
            "room_query": room,
            "attendee_queries": [],
            "description": None,
        },
        "update": None,
    }


def request(operation, action="CREATE", *, incomplete=False, room=None):
    return {
        "schema_version": "meeting.request.v1",
        "operation_id": operation,
        "intent": intent(action, incomplete=incomplete, room=room),
    }


class FakeProvider:
    def __init__(self):
        self.meetings = {}
        self.created = 0
        self.modified = 0
        self.simple_modified = 0
        self.fail_next_create = False
        self.available = True

    def scheduled(self, actor):
        return [
            value for value in self.meetings.values()
            if value["userId"] == actor.user_id
        ]

    def availability(self, actor, start, minutes):
        return [{
            "parties": "25",
            "count_available": "1" if self.available else "0",
            "count_total": "2",
        }]

    def rooms(self, actor):
        return [{"roomId": 1001, "roomParties": 25, "confList": []}]

    def detail(self, actor, conf_id):
        if conf_id not in self.meetings:
            raise ProviderError("401")
        return self.meetings[conf_id].copy()

    def create(self, actor, *, title, start, minutes, parties, room_id=None):
        self.created += 1
        if self.fail_next_create:
            self.fail_next_create = False
            raise ProviderUnknown("timeout")
        conf_id = 6000 + self.created
        self.meetings[conf_id] = {
            "confId": conf_id, "confNumber": f"880{conf_id}",
            "confName": title, "startTime": utc_form_time(start),
            "duration": minutes, "confParties": parties, "userId": actor.user_id,
            "confStatus": 0, "joinUrl": f"https://example.invalid/j/{conf_id}",
            "roomId": room_id,
        }
        return self.meetings[conf_id].copy()

    def modify(self, actor, old, *, title, start, minutes, parties, room_id=None):
        self.modified += 1
        item = self.meetings[int(old["confId"])]
        item.update({
            "confName": title,
            "startTime": utc_form_time(start),
            "duration": minutes, "confParties": parties,
        })
        if room_id is not None:
            item["roomId"] = room_id
        return item.copy()

    def modify_simple(self, actor, old, *, title):
        self.simple_modified += 1
        item = self.meetings[int(old["confId"])]
        item["confName"] = title
        return item.copy()


def service(tmp_path, *, enabled=True, provider=None):
    cfg = settings(tmp_path, enabled=enabled)
    fake = provider or FakeProvider()
    return MeetingService(cfg, StateStore(cfg.db_path), fake), fake


def update_request(op, conf_id, *, shift=60, changes=None):
    return {
        "schema_version": "meeting.request.v1",
        "operation_id": op,
        "intent": {
            "schema_version": "meeting.intent.v1",
            "action": "UPDATE",
            "target": {"meeting_id": str(conf_id), "search_text": None},
            "meeting": None,
            "update": {"time_shift_minutes": shift, "changes": changes or {}},
        },
    }


def test_identity_requires_valid_gateway_signature_and_same_corp(tmp_path):
    cfg = settings(tmp_path)
    headers = sign_identity(ACTOR, cfg.identity_secret, issued_at=1_000_000)
    assert verify_identity(headers, cfg, now=1_000_000) == ACTOR
    with pytest.raises(IdentityError):
        verify_identity({"X-Meeting-Actor": headers["X-Meeting-Actor"]}, cfg, now=1_000_000)
    with pytest.raises(IdentityError):
        verify_identity(headers, cfg, now=1_000_100)
    forged = dict(headers)
    forged["X-Meeting-Signature"] = "0" * 64
    with pytest.raises(IdentityError):
        verify_identity(forged, cfg, now=1_000_000)


def test_bizvideo_form_token_and_gmt(tmp_path):
    cfg = settings(tmp_path)
    captured = []

    def handler(req):
        captured.append(req)
        return httpx.Response(200, json={"status": 100, "data": {"confId": 6001}})

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        provider = BizVideoProvider(cfg, client)
        start = datetime(2026, 12, 1, 14, 0, tzinfo=timezone(timedelta(hours=8)))
        provider.create(
            ACTOR, title="联调测试", start=start, minutes=60, parties=25
        )

    req = captured[0]
    assert req.method == "POST"
    assert req.url.path.endswith("/confReservation")
    assert req.headers["content-type"].startswith("application/x-www-form-urlencoded")
    fields = parse_qs(req.content.decode())
    assert fields["startTime"] == ["2026-12-01 06:00:00"]
    assert fields["userId"] == [ACTOR.user_id]
    stamp = fields["timeStamp"][0]
    expected = hashlib.md5(f"{ACTOR.user_id}|{cfg.api_key}|{stamp}".encode()).hexdigest().upper()
    assert fields["token"] == [expected]


def test_create_is_idempotent_and_rejects_payload_change(tmp_path):
    svc, provider = service(tmp_path)
    data = request("op_create_case_0001")
    first = svc.submit(ACTOR, data)
    assert first["status"] == "COMMITTED"
    assert first["confirmed_meeting"]["duration_minutes"] == 60
    assert provider.created == 1
    assert svc.submit(ACTOR, data) == first
    assert provider.created == 1
    changed = request("op_create_case_0001")
    changed["intent"]["meeting"]["title"] = "被篡改"
    assert svc.submit(ACTOR, changed)["status"] == "INVALID"
    assert svc.submit(OTHER, data)["status"] == "DENIED"
    assert provider.created == 1


def test_check_is_read_only_and_does_not_require_title(tmp_path):
    svc, provider = service(tmp_path, enabled=False)
    outcome = svc.submit(ACTOR, request("op_check_case_0001", "CHECK"))
    assert outcome["status"] == "AVAILABLE"
    assert provider.created == 0
    assert svc.submit(
        ACTOR, request("op_create_off_0001", "CREATE")
    )["status"] == "DENIED"


def test_missing_fields_continue_and_cross_user_isolation(tmp_path):
    svc, provider = service(tmp_path)
    data = request("op_create_partial_001", incomplete=True)
    first = svc.submit(ACTOR, data)
    assert first["status"] == "NEED_INPUT"
    pending = first["pending_request_id"]
    completion = (
        datetime.fromisoformat(data["intent"]["meeting"]["start_at"])
        + timedelta(hours=1)
    ).isoformat()
    follow = {
        "schema_version": "meeting.continue.v1",
        "operation_id": "op_continue_valid_001",
        "pending_request_id": pending,
        "expected_revision": 1,
        "decision": {"kind": "SUPPLY_FIELDS", "fields": {"end_at": completion}},
    }
    assert svc.continue_request(OTHER, follow)["status"] == "DENIED"
    answer = svc.continue_request(ACTOR, follow)
    assert answer["status"] == "COMMITTED"
    assert provider.created == 1
    assert svc.continue_request(ACTOR, follow) == answer
    follow["operation_id"] = "op_continue_second_01"
    assert svc.continue_request(ACTOR, follow)["status"] == "EXPIRED"


def test_invalid_supply_does_not_consume_pending(tmp_path):
    svc, provider = service(tmp_path)
    data = request("op_create_partial_002", incomplete=True)
    first = svc.submit(ACTOR, data)
    follow = {
        "schema_version": "meeting.continue.v1",
        "operation_id": "op_supply_invalid_001",
        "pending_request_id": first["pending_request_id"],
        "expected_revision": 1,
        "decision": {"kind": "SUPPLY_FIELDS", "fields": {"user_id": "hacker"}},
    }
    assert svc.continue_request(ACTOR, follow)["status"] == "INVALID"
    follow["operation_id"] = "op_supply_correct_001"
    follow["decision"]["fields"] = {
        "end_at": (
            datetime.fromisoformat(data["intent"]["meeting"]["start_at"])
            + timedelta(hours=1)
        ).isoformat()
    }
    assert svc.continue_request(ACTOR, follow)["status"] == "COMMITTED"
    assert provider.created == 1


def test_update_relative_and_title_only(tmp_path):
    svc, provider = service(tmp_path)
    initial = svc.submit(ACTOR, request("op_create_updatable01"))
    conf_id = int(initial["meeting_id"])
    previous = provider.meetings[conf_id]["startTime"]
    shifted = svc.submit(
        ACTOR, update_request(
            "op_update_shift_0001", conf_id, shift=60, changes={"title": "新标题"},
        )
    )
    assert shifted["status"] == "COMMITTED"
    assert provider.modified == 1
    assert provider.created == 1
    assert provider.meetings[conf_id]["confName"] == "新标题"
    assert provider.meetings[conf_id]["startTime"] != previous
    only_title = svc.submit(
        ACTOR, update_request(
            "op_update_name_0001", conf_id, shift=None,
            changes={"title": "最终标题"},
        )
    )
    assert only_title["status"] == "COMMITTED"
    assert provider.simple_modified == 1
    assert provider.modified == 1


def test_user_conflict_and_physical_room_rejection(tmp_path):
    svc, provider = service(tmp_path)
    first = svc.submit(ACTOR, request("op_create_first_0001"))
    assert first["status"] == "COMMITTED"
    second = svc.submit(ACTOR, request("op_create_second_001"))
    assert second["status"] == "CONFLICT"
    assert second["pending_request_id"]
    assert provider.created == 1
    invalid = svc.submit(
        OTHER, request("op_physical_room_001", room="A301")
    )
    assert invalid["status"] == "INVALID"
    assert provider.created == 1


def test_unknown_is_never_automatically_replayed(tmp_path):
    fake = FakeProvider()
    fake.fail_next_create = True
    svc, provider = service(tmp_path, provider=fake)
    data = request("op_unknown_timeout_01")
    assert svc.submit(ACTOR, data)["status"] == "UNKNOWN"
    assert svc.submit(ACTOR, data)["status"] == "UNKNOWN"
    assert provider.created == 1
    assert svc.get_operation(ACTOR, {
        "schema_version": "meeting.operation-query.v1",
        "operation_id": "op_unknown_timeout_01",
    })["status"] == "UNKNOWN"


def test_sqlite_restart_restores_operation_ledger(tmp_path):
    svc, fake = service(tmp_path)
    data = request("op_create_restart_01")
    before = svc.submit(ACTOR, data)
    same = MeetingService(svc.settings, StateStore(svc.settings.db_path), fake)
    assert same.submit(ACTOR, data) == before
    assert fake.created == 1


@pytest.mark.parametrize(
    ("status_code", "payload", "expected"),
    [
        (503, {"status": 100}, ProviderUnknown),
        (200, {"status": 103}, ProviderUnknown),
        (200, {"status": 202}, ProviderError),
    ],
)
def test_provider_write_uncertainty_is_not_reported_as_definite_failure(
    tmp_path, status_code, payload, expected
):
    """HTTP 5xx / server-internal status after a write may hide a successful booking."""
    cfg = settings(tmp_path)
    transport = httpx.MockTransport(
        lambda req: httpx.Response(status_code, json=payload)
    )
    with httpx.Client(transport=transport) as client:
        provider = BizVideoProvider(cfg, client)
        with pytest.raises(expected):
            provider.create(
                ACTOR, title="测试会", start=datetime_future(),
                minutes=60, parties=25,
            )


def test_provider_malformed_write_reply_is_unknown_but_read_error_is_not(tmp_path):
    """会畅写响应损坏不应诱导重试；只读接口故障可明确归类。"""
    cfg = settings(tmp_path)
    with httpx.Client(
        transport=httpx.MockTransport(
            lambda req: httpx.Response(
                200, content=b"not-json", headers={"content-type": "application/json"}
            )
        )
    ) as client:
        provider = BizVideoProvider(cfg, client)
        with pytest.raises(ProviderUnknown):
            provider.create(
                ACTOR, title="测试会", start=datetime_future(),
                minutes=60, parties=25,
            )
        with pytest.raises(ProviderError):
            provider.scheduled(ACTOR)
