"""业务层：标准化会议意图到会畅账号模式的确定性执行和恢复。"""

import hashlib
import json
import re
from datetime import UTC, datetime, timedelta
from typing import Any

from .bizvideo import (
    BizVideoProvider,
    ProviderError,
    ProviderUnknown,
    parse_provider_time,
)
from .contract import ContractValidationError, validate_payload
from .identity import Actor
from .settings import Settings
from .state import StateError, StateStore

_ROOM = re.compile(r"^bizvideo-room:([1-9]\d*)$")
_BAD_TITLE = re.compile(r'[\\/:*?？"<>\r\n]')


def result(
    op_id: str, status: str, message: str, *, meeting_id: str | None = None,
    pending_id: str | None = None, revision: int | None = None,
    expires_at: str | None = None, options: list[dict] | None = None,
    conflicts: list[dict] | None = None, error_code: str | None = None,
    confirmed: dict | None = None,
) -> dict[str, Any]:
    """构造业务结果并通过正式结果契约校验。"""
    value: dict[str, Any] = {
        "schema_version": "meeting.result.v1",
        "operation_id": op_id,
        "status": status,
        "meeting_id": meeting_id,
        "pending_request_id": pending_id,
        "pending_revision": revision,
        "expires_at": expires_at,
        "message": message,
        "conflicts": conflicts or [],
        "options": options or [],
        "error": (
            {
                "code": error_code,
                "message": message,
                "retryable": False,
            }
            if error_code else None
        ),
    }
    if confirmed is not None:
        value["confirmed_meeting"] = confirmed
    validate_payload("result", value)
    return value


def _fingerprint(payload: Any) -> str:
    """计算稳定请求摘要，阻止同操作号被用于不同请求。"""
    text = json.dumps(payload, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _date(value: str) -> datetime:
    """解析带偏移的业务时间并统一为 UTC 瞬时。"""
    parsed = datetime.fromisoformat(value)
    if parsed.tzinfo is None:
        raise ValueError("时间缺失时区")
    return parsed.astimezone(UTC)


def _interval(start: datetime, end: datetime) -> int:
    """要求未来开始时间与正整数分钟时长。"""
    span = (end - start).total_seconds()
    if span <= 0 or span % 60 != 0:
        raise ValueError("会议时长必须是正整数分钟")
    if start <= datetime.now(UTC):
        raise ValueError("会议开始时间必须在未来")
    return int(span // 60)


def _overlap(first: datetime, second: datetime, start: datetime, end: datetime) -> bool:
    """按半开时间区间判断会议是否重叠。"""
    return first < end and start < second


class MeetingService:
    def __init__(
        self, settings: Settings, store: StateStore,
        provider: BizVideoProvider,
    ):
        """初始化本模块所需的状态与依赖。"""
        self.settings = settings
        self.store = store
        self.provider = provider

    def _pending(
        self, actor: Actor, op_id: str, intent: dict, status: str,
        message: str, *, options: list[dict] | None = None,
        conflicts: list[dict] | None = None,
    ) -> dict:
        """持久化原申请和候选，仅向调用方公开必要选项。"""
        internal = options or []
        pending_id, revision, expires = self.store.create_pending(
            actor, intent, internal
        )
        public_options = [
            {"option_id": item["option_id"], "label": item["label"]}
            for item in internal
        ]
        return result(
            op_id, status, message, pending_id=pending_id,
            revision=revision, expires_at=expires,
            options=public_options, conflicts=conflicts,
        )

    def _complete(self, actor: Actor, op_id: str, conf_id: int) -> dict:
        """写后回读并核对会议身份；本阶段失败只能进入 UNKNOWN。"""
        # 创建/修改写入后回读权威详情，避免从原始 LLM 输入宣布结果。
        try:
            meeting = self.provider.detail(actor, conf_id)
            if (
                str(meeting.get("userId", "")) != actor.user_id
                or str(meeting.get("confId", "")) != str(conf_id)
            ):
                raise ProviderUnknown("会畅写后回读的用户或会议 ID 不匹配")
            number = meeting["confNumber"]
            duration = meeting["duration"]
            if (
                isinstance(number, bool) or not isinstance(number, (str, int))
                or isinstance(duration, bool) or not str(duration).isdecimal()
            ):
                raise ValueError("会议号或时长缺少有效值")
            confirmed = {
                "meeting_id": str(meeting["confId"]),
                "meeting_number": str(number),
                "title": meeting["confName"],
                "start_at": parse_provider_time(str(meeting["startTime"])).isoformat(),
                "duration_minutes": int(duration),
                "join_url": meeting["joinUrl"],
            }
            return result(
                op_id, "COMMITTED", "会畅已确认会议操作成功",
                meeting_id=str(conf_id), confirmed=confirmed,
            )
        except (ProviderError, KeyError, TypeError, ValueError) as exc:
            # ValueError 包含结果契约校验错误，不能将已写入误报为 INVALID。
            raise ProviderUnknown("会畅写后详情无法确认，需核实原操作") from exc

    def _user_conflict(
        self, actor: Actor, start: datetime, end: datetime,
        exclude_id: str | None = None,
    ) -> bool:
        """检查当前用户其他预约与目标时段的交集。"""
        for item in self.provider.scheduled(actor):
            try:
                if exclude_id is not None and str(item.get("confId")) == exclude_id:
                    continue
                existing_start = parse_provider_time(str(item["startTime"]))
                existing_end = existing_start + timedelta(
                    minutes=int(item["duration"])
                )
            except (KeyError, TypeError, ValueError) as exc:
                raise ProviderError("PROVIDER_RESPONSE", "会畅会议列表时间无效") from exc
            if _overlap(existing_start, existing_end, start, end):
                return True
        return False

    @staticmethod
    def _room_id(query: str | None) -> int | None:
        """仅解析明确的会畅虚拟资源标识，拒绝实体会议室文本。"""
        if query is None:
            return None
        match = _ROOM.fullmatch(query)
        if match is None:
            raise ValueError(
                "仅支持会畅虚拟资源 bizvideo-room:<roomId>；A301 等实体会议室尚未接入"
            )
        return int(match.group(1))

    def _room_available(
        self, actor: Actor, room_id: int, start: datetime, end: datetime,
        parties: int, exclude_id: str | None = None,
    ) -> bool:
        """检查指定虚拟资源容量及排除原会议后的占用。"""
        for room in self.provider.rooms(actor):
            if str(room.get("roomId")) != str(room_id):
                continue
            if int(room.get("roomParties", 0)) < parties:
                return False
            for meeting in room.get("confList", []):
                if exclude_id is not None and str(meeting.get("confId")) == exclude_id:
                    continue
                begin = parse_provider_time(str(meeting["startTime"]))
                finish = begin + timedelta(minutes=int(meeting["duration"]))
                if _overlap(begin, finish, start, end):
                    return False
            return True
        return False

    def _pool_available(
        self, actor: Actor, start: datetime, minutes: int, parties: int
    ) -> bool:
        """按受控容量检查会畅资源池，拒绝损坏响应。"""
        pools = self.provider.availability(actor, start, minutes)
        try:
            return any(
                int(item["parties"]) >= parties and int(item["count_available"]) > 0
                for item in pools
            )
        except (KeyError, ValueError, TypeError) as exc:
            raise ProviderError("PROVIDER_RESPONSE", "会议可用资源格式异常") from exc

    def _meeting_parameters(
        self, meeting: dict, require_title: bool,
    ) -> tuple[str, datetime, datetime, int] | dict:
        """检查必要字段与能力限制并计算可执行的会议参数。"""
        required = ("title", "start_at", "end_at") if require_title else (
            "start_at", "end_at"
        )
        missing = [name for name in required if not meeting.get(name)]
        if missing:
            return {"missing": missing}
        if meeting.get("attendee_queries") or meeting.get("description") is not None:
            raise ValueError(
                "会畅预约接口未确认支持参会者邀请或会议描述，不能静默丢弃这些字段"
            )
        title = meeting.get("title") or "空闲查询"
        if _BAD_TITLE.search(title):
            raise ValueError("会议名称含会畅不支持的特殊字符")
        start = _date(meeting["start_at"])
        end = _date(meeting["end_at"])
        return title, start, end, _interval(start, end)

    def _create_or_check(
        self, actor: Actor, op_id: str, intent: dict,
    ) -> dict:
        """执行预约前检查；CHECK 只读，CREATE 受写开关限制。"""
        meeting = intent["meeting"]
        params = self._meeting_parameters(
            meeting, require_title=intent["action"] == "CREATE"
        )
        if isinstance(params, dict):
            return self._pending(
                actor, op_id, intent, "NEED_INPUT",
                "请补充：" + "、".join(params["missing"]),
            )
        title, start, end, minutes = params
        room_id = self._room_id(meeting.get("room_query"))
        if intent["action"] == "CREATE" and not self.settings.write_enabled:
            return result(
                op_id, "DENIED", "真实会议写入尚未启用",
                error_code="WRITE_DISABLED",
            )
        if self._user_conflict(actor, start, end):
            status = "UNAVAILABLE" if intent["action"] == "CHECK" else "CONFLICT"
            if status == "CONFLICT":
                return self._pending(
                    actor, op_id, intent, "CONFLICT",
                    "该用户在所选时间段已有预约会议",
                    conflicts=[{"type": "OTHER", "resource_label": "用户会议时段"}],
                )
            return result(op_id, status, "当前用户的会议时间冲突")
        available = (
            self._room_available(
                actor, room_id, start, end, self.settings.default_parties
            )
            if room_id is not None else self._pool_available(
                actor, start, minutes, self.settings.default_parties
            )
        )
        if not available:
            if intent["action"] == "CHECK":
                return result(op_id, "UNAVAILABLE", "指定时段无符合容量的可用会议资源")
            return self._pending(
                actor, op_id, intent, "CONFLICT", "指定时段无符合容量的可用会议资源",
                conflicts=[{"type": "ROOM", "resource_label": "会畅虚拟资源"}],
            )
        if intent["action"] == "CHECK":
            return result(op_id, "AVAILABLE", "当前查询显示资源可用，最终以预约提交为准")
        try:
            created = self.provider.create(
                actor, title=title, start=start, minutes=minutes,
                parties=self.settings.default_parties, room_id=room_id,
            )
        except ProviderError as exc:
            if exc.code in ("202", "205"):
                return self._pending(
                    actor, op_id, intent, "CONFLICT", "会畅最终提交时返回会议冲突",
                    conflicts=[{"type": "ROOM", "resource_label": "会畅会议资源"}],
                )
            raise
        return self._complete(actor, op_id, int(created["confId"]))

    def _resolve_target(
        self, actor: Actor, op_id: str, intent: dict
    ) -> str | dict:
        """定位本人会议；多候选时要求用户明确选择。"""
        target = intent.get("target")
        if not target:
            return self._pending(
                actor, op_id, intent, "NEED_INPUT", "请说明要修改的会议"
            )
        explicit = target.get("meeting_id")
        if explicit:
            value = explicit.removeprefix("meeting_")
            if not value.isdecimal() or int(value) <= 0:
                raise ValueError("会议 ID 必须使用会畅真实 confId")
            return str(int(value))
        search = (target.get("search_text") or "").strip().casefold()
        if not search:
            return self._pending(
                actor, op_id, intent, "NEED_INPUT", "请提供会议名称或 ID"
            )
        matches = [
            item for item in self.provider.scheduled(actor)
            if search in str(item.get("confName", "")).casefold()
        ]
        if not matches:
            return result(
                op_id, "NOT_FOUND", "当前用户没有匹配的待开始会议",
                error_code="MEETING_NOT_FOUND",
            )
        if len(matches) > 1:
            options = [
                {
                    "option_id": f"meeting_{item['confId']}",
                    "meeting_id": str(item["confId"]),
                    "label": str(item.get("confName", "未命名会议")),
                }
                for item in matches[:20]
            ]
            if len(matches) > len(options):
                return result(
                    op_id, "INVALID", "匹配会议过多，请提供更明确的名称或 ID",
                    error_code="TOO_MANY_MATCHES",
                )
            return self._pending(
                actor, op_id, intent, "NEED_SELECTION",
                "匹配到多场会议，请选择正确的会议",
                options=options,
            )
        return str(matches[0]["confId"])

    def _update(self, actor: Actor, op_id: str, intent: dict) -> dict:
        """读取原会议、检查所有权并按差量更新同一会议。"""
        resolved = self._resolve_target(actor, op_id, intent)
        if isinstance(resolved, dict):
            return resolved
        if intent.get("update") is None:
            return self._pending(
                actor, op_id, intent, "NEED_INPUT", "请说明需要修改的会议字段"
            )
        old = self.provider.detail(actor, int(resolved))
        if str(old.get("userId", "")) != actor.user_id:
            return result(
                op_id, "DENIED", "不能修改其他用户的会议",
                error_code="MEETING_OWNER_MISMATCH",
            )
        if str(old.get("confStatus")) != "0":
            return result(
                op_id, "INVALID", "只能修改尚未开始的预约会议",
                error_code="INVALID_MEETING_STATUS",
            )
        try:
            title = str(old["confName"])
            start = parse_provider_time(str(old["startTime"]))
            minutes = int(old["duration"])
            parties = int(old["confParties"])
            if minutes < 1 or parties < 1:
                raise ValueError("会议信息缺少有效时长或方数")
        except (KeyError, ValueError, TypeError) as exc:
            raise ProviderError("PROVIDER_RESPONSE", "原会议必要字段缺失") from exc
        end = start + timedelta(minutes=minutes)
        update = intent["update"]
        shift = update["time_shift_minutes"]
        changes = update["changes"]
        if "attendee_queries" in changes or "description" in changes:
            raise ValueError("会畅接口尚未确认支持修改与会人或会议描述")
        if "title" in changes:
            title = changes["title"]
        if _BAD_TITLE.search(title):
            raise ValueError("会议名称含不支持的特殊字符")
        if shift is not None:
            start += timedelta(minutes=shift)
            end += timedelta(minutes=shift)
        elif "start_at" in changes:
            start = _date(changes["start_at"])
            # 只改开始时间时保持原持续时长。
            if "end_at" not in changes:
                end = start + timedelta(minutes=minutes)
        if "end_at" in changes:
            end = _date(changes["end_at"])
        minutes = _interval(start, end)
        room_id = self._room_id(changes.get("room_query"))
        changed_time = (
            shift is not None or "start_at" in changes or "end_at" in changes
        )
        if not self.settings.write_enabled:
            return result(
                op_id, "DENIED", "真实会议写入尚未启用",
                error_code="WRITE_DISABLED",
            )
        if not changed_time and room_id is None:
            updated = self.provider.modify_simple(actor, old, title=title)
            return self._complete(actor, op_id, int(updated["confId"]))
        if changed_time and self._user_conflict(
            actor, start, end, exclude_id=resolved
        ):
            return self._pending(
                actor, op_id, intent, "CONFLICT", "修改后与当前用户其他会议冲突",
            )
        if room_id is not None:
            available = self._room_available(
                actor, room_id, start, end, parties, exclude_id=resolved
            )
        else:
            available = self._pool_available(actor, start, minutes, parties)
        if not available:
            return self._pending(
                actor, op_id, intent, "CONFLICT", "修改后的会议资源不可用",
            )
        try:
            updated = self.provider.modify(
                actor, old, title=title, start=start,
                minutes=minutes, parties=parties, room_id=room_id,
            )
        except ProviderError as exc:
            if exc.code in ("202", "205"):
                return self._pending(
                    actor, op_id, intent, "CONFLICT", "会畅最终修改时返回冲突",
                )
            raise
        return self._complete(actor, op_id, int(updated["confId"]))

    def _execute(self, actor: Actor, op_id: str, intent: dict) -> dict:
        """按已校验意图分发创建、修改与空闲查询。"""
        action = intent["action"]
        if action in ("CREATE", "CHECK"):
            return self._create_or_check(actor, op_id, intent)
        if action == "UPDATE":
            return self._update(actor, op_id, intent)
        return result(
            op_id, "INVALID", "不支持的会议操作，不会执行写入",
            error_code="UNSUPPORTED_ACTION",
        )

    def _run(
        self, actor: Actor, op_id: str, payload: dict, execute: Any,
    ) -> dict:
        """持久化占用操作号并保存结果，不自动重放未知写入。"""
        try:
            previous = self.store.begin(actor, op_id, _fingerprint(payload))
        except StateError as exc:
            return result(
                op_id, "DENIED" if exc.code == "DENIED" else "INVALID",
                "操作标识冲突或不属于当前用户", error_code=exc.code,
            )
        if previous is not None:
            if "schema_version" in previous:
                return previous
            return result(
                op_id, previous["status"], "已有操作正在执行或结果尚未核实",
            )
        try:
            outcome = execute()
        except (ValueError, ContractValidationError) as exc:
            outcome = result(
                op_id, "INVALID", str(exc), error_code="BUSINESS_VALIDATION"
            )
        except ProviderError as exc:
            outcome = result(
                op_id, "FAILED", "会畅接口返回失败：" + exc.code,
                error_code=exc.code,
            )
        except ProviderUnknown:
            outcome = result(
                op_id, "UNKNOWN", "远端操作结果不确定，禁止自动重复写入",
            )
        except Exception:
            # 意外失败也不能把一次可能已成功的写操作判断为失败。
            outcome = result(
                op_id, "UNKNOWN", "请求结果无法确定，请人工核实会畅会议列表",
            )
        self.store.finish(op_id, outcome)
        return outcome

    def submit(self, actor: Actor, request: dict) -> dict:
        """校验正式提交契约后进入幂等业务入口。"""
        validate_payload("request", request)
        op_id = request["operation_id"]
        return self._run(
            actor, op_id, request,
            lambda: self._execute(actor, op_id, request["intent"]),
        )

    def continue_request(self, actor: Actor, request: dict) -> dict:
        """验证申请持有人与版本，再处理补参、选择或取消。"""
        validate_payload("continue", request)
        op_id = request["operation_id"]
        # 他人或失效申请不能抢占操作号；已记录操作仍可恢复消费前的原结果。
        try:
            existing = self.store.operation(actor, op_id)
            if existing is None:
                self.store.read_pending(
                    actor, request["pending_request_id"], request["expected_revision"]
                )
        except StateError as exc:
            status = (
                "DENIED" if exc.code == "DENIED"
                else "EXPIRED" if exc.code in ("EXPIRED", "STALE_PENDING")
                else "NOT_FOUND"
            )
            return result(
                op_id, status, "待处理申请不存在、已失效或无权限",
                error_code=exc.code,
            )

        def run() -> dict:
            """合并用户决策并消费申请，校验失败时恢复可纠正状态。"""
            intent, options = self.store.read_pending(
                actor, request["pending_request_id"], request["expected_revision"]
            )
            decision = request["decision"]
            kind = decision["kind"]
            if kind == "CANCEL":
                self.store.consume_pending(
                    actor, request["pending_request_id"], request["expected_revision"]
                )
                return result(op_id, "CANCELLED", "已取消待处理申请，不影响真实会议")
            if kind == "SELECT_OPTION":
                item = next(
                    (it for it in options if it["option_id"] == decision["option_id"]),
                    None,
                )
                if item is None or "meeting_id" not in item:
                    raise ValueError("选项已失效，请重新发起申请")
                intent["target"] = {
                    "meeting_id": item["meeting_id"], "search_text": None
                }
            elif kind == "SUPPLY_FIELDS":
                fields = decision["fields"]
                if intent["action"] in ("CREATE", "CHECK"):
                    allowed = {
                        "title", "start_at", "end_at", "timezone",
                        "room_query", "attendee_queries", "description",
                    }
                    if not fields or set(fields) - allowed:
                        raise ValueError("补充字段超出允许范围")
                    intent["meeting"].update(fields)
                elif intent["action"] == "UPDATE":
                    if not fields or set(fields) - {"target", "update"}:
                        raise ValueError("修改申请只能补充 target 或完整 update")
                    intent.update(fields)
                else:
                    raise ValueError("此申请不支持继续处理")
            else:
                raise ValueError("不支持的后续决策")
            validate_payload("intent", intent)
            self.store.consume_pending(
                actor, request["pending_request_id"], request["expected_revision"]
            )
            try:
                return self._execute(actor, op_id, intent)
            except ValueError:
                # 输入尚未触发写入即被业务校验拒绝，允许原持有人纠正补参。
                # 写后解析/校验失败由 ProviderUnknown 隔离，不能在此释放申请。
                self.store.release_pending(
                    actor, request["pending_request_id"], request["expected_revision"]
                )
                raise

        def execute() -> dict:
            """将申请状态冲突转换为明确业务结果。"""
            try:
                return run()
            except StateError as exc:
                status = (
                    "DENIED" if exc.code == "DENIED"
                    else "EXPIRED" if exc.code in ("EXPIRED", "STALE_PENDING")
                    else "NOT_FOUND"
                )
                return result(
                    op_id, status, "待处理申请不存在、已失效或无权限",
                    error_code=exc.code,
                )

        return self._run(actor, op_id, request, execute)

    def get_operation(self, actor: Actor, request: dict) -> dict:
        """仅返回本人已存操作状态，不触发供应商写入。"""
        validate_payload("operation-query", request)
        op_id = request["operation_id"]
        try:
            stored = self.store.operation(actor, op_id)
        except StateError as exc:
            return result(
                op_id, "DENIED", "无法访问其他用户的操作记录",
                error_code=exc.code,
            )
        if stored is None:
            return result(
                op_id, "NOT_FOUND", "没有找到此操作",
                error_code="OPERATION_NOT_FOUND",
            )
        if "schema_version" in stored:
            return stored
        return result(
            op_id, stored["status"], "操作尚未完成或结果尚未核实",
        )
