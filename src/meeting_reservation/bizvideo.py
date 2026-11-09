"""会畅智云账号模式 OpenAPI v1.0.10 的最小 Provider Adapter。

只允许受控端点；GMT、form POST、MD5 Token 以及 status==100 均在此收口。
"""

import hashlib
import time
from datetime import datetime, timezone
from threading import Lock
from typing import Any

import httpx

from .identity import Actor
from .settings import Settings


class ProviderError(RuntimeError):
    def __init__(self, code: str, message: str = "会议服务拒绝请求"):
        super().__init__(message)
        self.code = code


class ProviderUnknown(RuntimeError):
    """远端可能已经处理请求，但客户端没有得到确定返回值。"""


def utc_form_time(value: datetime) -> str:
    if value.tzinfo is None:
        raise ValueError("时间必须含明确时区")
    return value.astimezone(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")


def parse_provider_time(value: str) -> datetime:
    """会畅返回的无时区字符串根据文档解释为 GMT。"""
    return datetime.strptime(value.strip(), "%Y-%m-%d %H:%M:%S").replace(
        tzinfo=timezone.utc
    )


class BizVideoProvider:
    def __init__(self, settings: Settings, client: httpx.Client | None = None):
        self.settings = settings
        self._stamp_lock = Lock()
        self._last_stamp = 0
        self.client = client or httpx.Client(
            timeout=settings.timeout_seconds, follow_redirects=False
        )

    def _request(
        self, method: str, path: str, actor: Actor, params: dict[str, Any],
        *, mutation: bool = False,
    ) -> dict[str, Any]:
        self.settings.require_provider()
        # Tokens are single-use: calls in the same millisecond cannot reuse
        # the same userId/APIKey/timestamp digest on this server instance.
        with self._stamp_lock:
            stamp = max(time.time_ns() // 1_000_000, self._last_stamp + 1)
            self._last_stamp = stamp
        token = hashlib.md5(
            f"{actor.user_id}|{self.settings.api_key}|{stamp}".encode("utf-8")
        ).hexdigest().upper()
        data = {
            **params,
            "userId": actor.user_id,
            "timeStamp": stamp,
            "token": token,
            "siteSign": self.settings.site_sign,
        }
        # 不允许业务输入改变受控端点或身份字段。
        try:
            resp = self.client.request(
                method,
                self.settings.base_url + "/" + path,
                params=data if method == "GET" else None,
                data=data if method == "POST" else None,
                timeout=self.settings.timeout_seconds,
            )
            resp.raise_for_status()
            payload = resp.json()
        except (httpx.TimeoutException, httpx.TransportError) as exc:
            if mutation:
                raise ProviderUnknown("会畅写请求超时或网络中断，结果待核实") from exc
            raise ProviderError("PROVIDER_NETWORK", "会畅读取请求网络异常") from exc
        except httpx.HTTPStatusError as exc:
            if mutation and exc.response.status_code >= 500:
                raise ProviderUnknown("会畅写请求返回服务器错误，结果待核实") from exc
            raise ProviderError("PROVIDER_HTTP", "会畅返回 HTTP 错误") from exc
        except ValueError as exc:
            if mutation:
                raise ProviderUnknown("会畅写请求响应不可解析，结果待核实") from exc
            raise ProviderError("PROVIDER_RESPONSE", "会畅读取响应格式异常") from exc
        if not isinstance(payload, dict):
            if mutation:
                raise ProviderUnknown("会畅写请求返回非对象，结果待核实")
            raise ProviderError("PROVIDER_RESPONSE", "会畅响应不是对象")
        status = str(payload.get("status"))
        if status != "100":
            if mutation and status in ("103", "112"):
                raise ProviderUnknown("会畅写请求返回不确定服务器状态，结果待核实")
            # 不透传内部错误正文，避免把用户/会议/服务端细节暴露给模型。
            raise ProviderError(status, "会畅返回业务失败状态：" + status)
        return payload

    def detail(self, actor: Actor, conf_id: int) -> dict[str, Any]:
        raw = self._request(
            "GET", "getConfDetailByConfId", actor, {"confId": conf_id}
        ).get("data")
        if not isinstance(raw, dict):
            raise ProviderError("PROVIDER_RESPONSE", "会议详情字段异常")
        return raw

    def scheduled(self, actor: Actor, max_pages: int = 20) -> list[dict[str, Any]]:
        result: list[dict[str, Any]] = []
        for page in range(1, max_pages + 1):
            raw = self._request(
                "POST", "getScheduledConfListByUserId", actor,
                {"pageNo": page, "pageSize": 100},
            )
            page_data = raw.get("data") or {}
            batch = page_data.get("confInfo", []) if isinstance(page_data, dict) else []
            if not isinstance(batch, list):
                raise ProviderError("PROVIDER_RESPONSE", "会议列表结构异常")
            result.extend(item for item in batch if isinstance(item, dict))
            total = int(raw.get("totalPage") or 1)
            if page >= total:
                return result
        raise ProviderError("PAGE_LIMIT", "会议列表超出安全分页上限")

    def availability(
        self, actor: Actor, start: datetime, minutes: int
    ) -> list[dict[str, Any]]:
        data = self._request(
            "GET", "getAvailableRoomsBySiteSign", actor,
            {"startTime": utc_form_time(start), "duration": minutes},
        ).get("data")
        if not isinstance(data, list):
            raise ProviderError("PROVIDER_RESPONSE", "会议资源数据异常")
        return data

    def rooms(self, actor: Actor) -> list[dict[str, Any]]:
        result: list[dict[str, Any]] = []
        for page in range(1, 21):
            raw = self._request(
                "GET", "getRoomListAndConfListBySiteSign", actor,
                {"pageNo": page, "pageSize": 100},
            )
            batch = raw.get("data")
            if not isinstance(batch, list):
                raise ProviderError("PROVIDER_RESPONSE", "会议室列表结构异常")
            result.extend(item for item in batch if isinstance(item, dict))
            if page >= int(raw.get("totalPage") or 1):
                return result
        raise ProviderError("PAGE_LIMIT", "会议室列表超出安全分页上限")

    def create(
        self, actor: Actor, *, title: str, start: datetime, minutes: int,
        parties: int, room_id: int | None = None,
    ) -> dict[str, Any]:
        data: dict[str, Any] = {
            "userName": actor.user_name,
            "confName": title,
            "startTime": utc_form_time(start),
            "duration": minutes,
        }
        if room_id is None:
            data.update({"confParties": parties, "upCompatible": "y"})
            path = "confReservation"
        else:
            data["roomId"] = room_id
            path = "confReservationByRoomId"
        result = self._request(
            "POST", path, actor, data, mutation=True
        ).get("data")
        if not isinstance(result, dict) or not result.get("confId"):
            raise ProviderUnknown("远端返回创建成功但缺少会议 ID")
        return result

    def modify_simple(
        self, actor: Actor, old: dict[str, Any], *, title: str,
    ) -> dict[str, Any]:
        data: dict[str, Any] = {
            "confId": int(old["confId"]),
            "confName": title,
        }
        for name in (
            "confPassword", "optionJbh", "optionVideoParticipants",
            "muteWhenJoining", "channelId",
        ):
            if name in old and old[name] is not None:
                data[name] = old[name]
        result = self._request(
            "POST", "confModify", actor, data, mutation=True
        ).get("data")
        if not isinstance(result, dict) or not result.get("confId"):
            raise ProviderUnknown("普通修改结果缺少会议 ID")
        return result

    def modify(
        self, actor: Actor, old: dict[str, Any], *,
        title: str, start: datetime, minutes: int, parties: int,
        room_id: int | None = None,
    ) -> dict[str, Any]:
        data: dict[str, Any] = {
            "confId": int(old["confId"]),
            "confName": title,
            "startTime": utc_form_time(start),
            "duration": minutes,
            "confParties": parties,
            "keepConfNo": 1,
            "upCompatible": "y",
        }
        # 原接口默认值可能覆盖原会议属性，按详情中实际存在的值保留。
        for name in (
            "confPassword", "optionJbh", "optionVideoParticipants",
            "beforeTime", "muteWhenJoining", "channelId",
        ):
            if name in old and old[name] is not None:
                data[name] = old[name]
        if room_id is not None:
            data["roomId"] = room_id
            path = "confModify2ByRoomId"
        else:
            path = "confModify2"
        result = self._request(
            "POST", path, actor, data, mutation=True
        ).get("data")
        if not isinstance(result, dict) or not result.get("confId"):
            raise ProviderUnknown("远端返回修改成功但缺少会议 ID")
        return result
