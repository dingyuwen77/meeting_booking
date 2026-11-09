"""独立 Fake Provider 业务回归：不能冒充真实会畅/ADP 联调。"""

import hashlib
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta, timezone
from threading import Barrier, Event
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
from meeting_reservation.state import StateError, StateStore

ACTOR = Actor("corp_example", "YNND", "测试员工")
OTHER = Actor("corp_example", "OTHER", "另一位员工")


def settings(tmp_path, *, enabled=True):
    """构造使用隔离临时数据库与虚构凭据的测试配置。"""
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
    """生成带明确时区的未来测试时刻。"""
    return datetime.now(UTC).replace(microsecond=0) + timedelta(hours=hours)


def intent(action="CREATE", *, incomplete=False, room=None):
    """构造符合正式契约的会议意图。"""
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
    """为测试意图附加稳定操作号。"""
    return {
        "schema_version": "meeting.request.v1",
        "operation_id": operation,
        "intent": intent(action, incomplete=incomplete, room=room),
    }


class FakeProvider:
    def __init__(self):
        """初始化本模块所需的状态与依赖。"""
        self.meetings = {}
        self.created = 0
        self.modified = 0
        self.simple_modified = 0
        self.fail_next_create = False
        self.available = True

    def scheduled(self, actor):
        """完整分页读取当前用户待开始会议，超过边界时明确失败。"""
        return [
            value for value in self.meetings.values()
            if value["userId"] == actor.user_id
        ]

    def availability(self, actor, start, minutes):
        """查询时段内会畅容量池的可用数量。"""
        return [{
            "parties": "25",
            "count_available": "1" if self.available else "0",
            "count_total": "2",
        }]

    def rooms(self, actor):
        """分页取得会畅虚拟资源及其会议占用。"""
        return [{"roomId": 1001, "roomParties": 25, "confList": []}]

    def detail(self, actor, conf_id):
        """读取指定会议的权威详情，格式异常时拒绝使用。"""
        if conf_id not in self.meetings:
            raise ProviderError("401")
        return self.meetings[conf_id].copy()

    def create(self, actor, *, title, start, minutes, parties, room_id=None):
        """按容量或指定虚拟资源提交预约，并检查写入确认。"""
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
        """提交原会议的时间与资源修改，保留已知配置。"""
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
        """只修改会议名称并保留已回读的相关选项。"""
        self.simple_modified += 1
        item = self.meetings[int(old["confId"])]
        item["confName"] = title
        return item.copy()


def service(tmp_path, *, enabled=True, provider=None):
    """组装生产业务层、真实 SQLite 与隔离供应商。"""
    cfg = settings(tmp_path, enabled=enabled)
    fake = provider or FakeProvider()
    return MeetingService(cfg, StateStore(cfg.db_path), fake), fake


def update_request(op, conf_id, *, shift=60, changes=None):
    """构造对原会议的差量修改请求。"""
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
    """验证缺失、篡改及过期身份均被拒绝。"""
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
    """验证生产适配器发出的表单、用户、GMT 与 Token。"""
    cfg = settings(tmp_path)
    captured = []

    def handler(req):
        """捕获本地 HTTP 请求并返回隔离测试响应。"""
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
    """验证同请求重试不重复创建，换用户或换内容被拒绝。"""
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
    """验证空闲检查无需标题且关闭写入仍可只读查询。"""
    svc, provider = service(tmp_path, enabled=False)
    outcome = svc.submit(ACTOR, request("op_check_case_0001", "CHECK"))
    assert outcome["status"] == "AVAILABLE"
    assert provider.created == 0
    assert svc.submit(
        ACTOR, request("op_create_off_0001", "CREATE")
    )["status"] == "DENIED"


def test_missing_fields_continue_and_cross_user_isolation(tmp_path):
    """验证补参仅能由原申请人执行且可幂等恢复。"""
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
    """验证非法补参不消耗原申请。"""
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
    """验证平移与名称修改均更新原会议并使用合适接口。"""
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
    """验证本人时间冲突及实体会议室输入不会创建会议。"""
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
    """验证未知写入可查询且不会自动重放。"""
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
    """验证重新创建存储对象后仍能恢复原操作结果。"""
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
    """写入后 HTTP 5xx 或内部故障可能掩盖已成功的预约。"""
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


def test_token_timestamp_is_unique_even_in_the_same_millisecond(tmp_path, monkeypatch):
    """会畅 token 只能使用一次，连续请求不能重复相同毫秒时间戳。"""
    import meeting_reservation.bizvideo as bizvideo

    cfg = settings(tmp_path)
    stamps = []

    def handler(req):
        """捕获本地 HTTP 请求并返回隔离测试响应。"""
        fields = parse_qs(req.content.decode())
        stamps.append(int(fields["timeStamp"][0]))
        return httpx.Response(200, json={"status": 100, "data": {"confId": 6001}})

    monkeypatch.setattr(
        bizvideo.time, "time_ns", lambda: 1_700_000_000_000_000_000
    )
    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        provider = BizVideoProvider(cfg, client)
        for _ in range(3):
            provider.create(
                ACTOR, title="测试会", start=datetime_future(),
                minutes=60, parties=25,
            )
    assert stamps == [
        1_700_000_000_000,
        1_700_000_000_001,
        1_700_000_000_002,
    ]


@pytest.mark.parametrize("failure", ["network", "invalid_summary", "wrong_id", "null_summary"])
@pytest.mark.parametrize("action", ["CREATE", "UPDATE"])
def test_successful_write_with_unconfirmed_readback_stays_unknown(
    tmp_path, monkeypatch, failure, action,
):
    """已执行的写入不能因回读故障或详情错配被报告为确定失败。"""
    svc, provider = service(tmp_path)
    if action == "UPDATE":
        initial = svc.submit(ACTOR, request("op_readback_initial_01"))
        data = update_request("op_readback_update_01", initial["meeting_id"])
    else:
        data = request("op_readback_create_01")
    original_detail = provider.detail

    def detail(actor, conf_id):
        """只在写后回读注入故障，保留 UPDATE 的原值读取。"""
        if action == "UPDATE" and not provider.modified:
            return original_detail(actor, conf_id)
        if failure == "network":
            raise ProviderError("PROVIDER_NETWORK")
        info = original_detail(actor, conf_id)
        if failure == "invalid_summary":
            info["duration"] = 0
        elif failure == "null_summary":
            info["confNumber"] = None
        else:
            info["confId"] = conf_id + 1
        return info

    monkeypatch.setattr(provider, "detail", detail)
    first = svc.submit(ACTOR, data)
    assert first["status"] == "UNKNOWN"
    assert svc.submit(ACTOR, data) == first
    assert provider.created == 1
    assert provider.modified == (1 if action == "UPDATE" else 0)


def test_business_invalid_supply_preserves_pending_for_correction(tmp_path):
    """时间等业务校验失败后，用户可以用新操作号纠正同一申请。"""
    svc, provider = service(tmp_path)
    data = request("op_supply_business_01", incomplete=True)
    first = svc.submit(ACTOR, data)
    follow = {
        "schema_version": "meeting.continue.v1",
        "operation_id": "op_supply_badtime_01",
        "pending_request_id": first["pending_request_id"],
        "expected_revision": 1,
        "decision": {"kind": "SUPPLY_FIELDS", "fields": {
            "end_at": (
                datetime.fromisoformat(data["intent"]["meeting"]["start_at"])
                + timedelta(seconds=30)
            ).isoformat(),
        }},
    }
    assert svc.continue_request(ACTOR, follow)["status"] == "INVALID"
    follow["operation_id"] = "op_supply_fixedtime_01"
    follow["decision"]["fields"]["end_at"] = (
        datetime.fromisoformat(data["intent"]["meeting"]["start_at"])
        + timedelta(hours=1)
    ).isoformat()
    assert svc.continue_request(ACTOR, follow)["status"] == "COMMITTED"
    assert provider.created == 1


@pytest.mark.parametrize("payload", [
    {"data": {"confId": 6001}},
    {"status": 100, "data": {"confId": "bad-id"}},
    {"status": 100, "data": {"confId": True}},
])
def test_malformed_write_confirmation_is_unknown(tmp_path, payload):
    """缺失业务状态或畸形会议号都不能证明写入失败。"""
    with httpx.Client(transport=httpx.MockTransport(
        lambda req: httpx.Response(200, json=payload)
    )) as client:
        provider = BizVideoProvider(settings(tmp_path), client)
        with pytest.raises(ProviderUnknown):
            provider.create(
                ACTOR, title="测试会", start=datetime_future(), minutes=60, parties=25,
            )


def test_concurrent_retry_does_not_submit_another_write(tmp_path, monkeypatch):
    """首个写入被受控阻塞时，同操作号并发重试只能查询执行状态。"""
    svc, provider = service(tmp_path)
    data = request("op_concurrent_same_01")
    entered, release = Event(), Event()
    original_create = provider.create

    def blocked_create(*args, **kwargs):
        """固定首次写入的交错位置，不用随机等待制造并发。"""
        entered.set()
        assert release.wait(5)
        return original_create(*args, **kwargs)

    monkeypatch.setattr(provider, "create", blocked_create)
    with ThreadPoolExecutor(max_workers=2) as pool:
        first = pool.submit(svc.submit, ACTOR, data)
        try:
            assert entered.wait(5)
            duplicate = pool.submit(svc.submit, ACTOR, data).result(timeout=5)
            assert duplicate["status"] == "IN_PROGRESS"
        finally:
            release.set()
        assert first.result(timeout=5)["status"] == "COMMITTED"
    assert provider.created == 1


def test_pending_has_one_winner_under_concurrent_consumption(tmp_path):
    """两个同时到达的申请消费只有一个成功，保护跨线程 SQLite 事务边界。"""
    svc, _ = service(tmp_path)
    pending, revision, _ = svc.store.create_pending(ACTOR, intent(), [])
    barrier = Barrier(2)

    def consume():
        """同步两个消费者进入各自的真实数据库事务。"""
        barrier.wait(timeout=5)
        try:
            svc.store.consume_pending(ACTOR, pending, revision)
            return "claimed"
        except StateError as exc:
            return exc.code

    with ThreadPoolExecutor(max_workers=2) as pool:
        outcomes = list(pool.map(lambda _: consume(), range(2)))
    assert sorted(outcomes) == ["STALE_PENDING", "claimed"]


def test_ambiguous_meeting_requires_selection_and_updates_only_chosen(tmp_path):
    """同名会议必须经保存的候选选择，再修改选定原会议。"""
    svc, provider = service(tmp_path)
    first = svc.submit(ACTOR, request("op_select_create_001"))
    second_data = request("op_select_create_002")
    for field in ("start_at", "end_at"):
        second_data["intent"]["meeting"][field] = (
            datetime.fromisoformat(second_data["intent"]["meeting"][field])
            + timedelta(days=1)
        ).isoformat()
    second = svc.submit(ACTOR, second_data)
    data = update_request("op_select_ambiguous01", first["meeting_id"], shift=None,
                          changes={"title": "选定会议"})
    data["intent"]["target"] = {"meeting_id": None, "search_text": "产品评审会"}
    pending = svc.submit(ACTOR, data)
    assert pending["status"] == "NEED_SELECTION"
    assert len(pending["options"]) == 2
    chosen = svc.continue_request(ACTOR, {
        "schema_version": "meeting.continue.v1", "operation_id": "op_select_continue01",
        "pending_request_id": pending["pending_request_id"], "expected_revision": 1,
        "decision": {"kind": "SELECT_OPTION", "option_id": f"meeting_{second['meeting_id']}"},
    })
    assert chosen["status"] == "COMMITTED"
    assert chosen["meeting_id"] == second["meeting_id"]
    assert provider.meetings[int(first["meeting_id"])]["confName"] == "产品评审会"
    assert provider.created == 2
