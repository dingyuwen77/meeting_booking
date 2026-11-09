"""会畅智云账号模式 OpenAPI v1.0.10 的最小 Provider Adapter。

只允许受控端点；GMT、form POST、MD5 Token 以及 status==100 均在此收口。
"""

import hashlib
import time
from datetime import UTC, datetime
from threading import Lock
from typing import Any

import httpx

from .identity import Actor
from .settings import Settings


class ProviderError(RuntimeError):
    def __init__(self, code: str, message: str = "会议服务拒绝请求"):
        """初始化本模块所需的状态与依赖。"""
        super().__init__(message)
        self.code = code


class ProviderUnknown(RuntimeError):
    """远端可能已经处理请求，但客户端没有得到确定返回值。"""


def utc_form_time(value: datetime) -> str:
    """将带时区时间转换为会畅要求的 GMT 表单字符串。"""
    if value.tzinfo is None:
        raise ValueError("时间必须含明确时区")
    return value.astimezone(UTC).strftime("%Y-%m-%d %H:%M:%S")


def parse_provider_time(value: str) -> datetime:
    """会畅返回的无时区字符串根据文档解释为 GMT。"""
    return datetime.strptime(value.strip(), "%Y-%m-%d %H:%M:%S").replace(
        tzinfo=UTC
    )


class BizVideoProvider:
    def __init__(self, settings: Settings, client: httpx.Client | None = None):
        """初始化本模块所需的状态与依赖。"""
        self.settings = settings
        self._owns_client = client is None
        self._stamp_lock = Lock()
        self._last_stamp = 0
        self.client = client or httpx.Client(
            timeout=settings.timeout_seconds, follow_redirects=False
        )

    def close(self) -> None:
        """释放本适配器创建的连接；外部注入连接仍由调用方负责。"""
        if self._owns_client:
            self.client.close()

    def _request(
        self, method: str, path: str, actor: Actor, params: dict[str, Any],
        *, mutation: bool = False,
    ) -> dict[str, Any]:
        """统一签名并提交会畅请求，区分确定失败与写入未知。"""
        self.settings.require_provider()
        # Token 只能使用一次，单实例内同毫秒调用也要使用不同时间戳。
        with self._stamp_lock:
            stamp = max(time.time_ns() // 1_000_000, self._last_stamp + 1)
            self._last_stamp = stamp
        token = hashlib.md5(
            f"{actor.user_id}|{self.settings.api_key}|{stamp}".encode()
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
            if mutation and (not status.isdecimal() or status in ("103", "112")):
                raise ProviderUnknown("会畅写请求返回不确定服务器状态，结果待核实")
            # 不透传内部错误正文，避免把用户/会议/服务端细节暴露给模型。
            raise ProviderError(status, "会畅返回业务失败状态：" + status)
        return payload

    @staticmethod
    def _write_result(payload: dict[str, Any], expected_id: int | None = None) -> dict:
        """写入确认必须有有效会议号，修改响应还必须属于原会议。"""
        data = payload.get("data")
        conf_id = data.get("confId") if isinstance(data, dict) else None
        if (
            isinstance(conf_id, bool)
            or not isinstance(conf_id, (str, int))
            or not str(conf_id).isdecimal()
            or int(conf_id) < 1
            or (expected_id is not None and int(conf_id) != expected_id)
        ):
            raise ProviderUnknown("会畅写入成功响应未包含可确认的会议 ID")
        return data

    def detail(self, actor: Actor, conf_id: int) -> dict[str, Any]:
        """读取指定会议的权威详情，格式异常时拒绝使用。"""
        raw = self._request(
            "GET", "getConfDetailByConfId", actor, {"confId": conf_id}
        ).get("data")
        if not isinstance(raw, dict):
            raise ProviderError("PROVIDER_RESPONSE", "会议详情字段异常")
        return raw

    def scheduled(self, actor: Actor, max_pages: int = 20) -> list[dict[str, Any]]:
        """完整分页读取当前用户待开始会议，超过边界时明确失败。"""
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
        """查询时段内会畅容量池的可用数量。"""
        data = self._request(
            "GET", "getAvailableRoomsBySiteSign", actor,
            {"startTime": utc_form_time(start), "duration": minutes},
        ).get("data")
        if not isinstance(data, list):
            raise ProviderError("PROVIDER_RESPONSE", "会议资源数据异常")
        return data

    def rooms(self, actor: Actor) -> list[dict[str, Any]]:
        """分页取得会畅虚拟资源及其会议占用。"""
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
        """按容量或指定虚拟资源提交预约，并检查写入确认。"""
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
        return self._write_result(self._request(
            "POST", path, actor, data, mutation=True
        ))

    def modify_simple(
        self, actor: Actor, old: dict[str, Any], *, title: str,
    ) -> dict[str, Any]:
        """只修改会议名称并保留已回读的相关选项。"""
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
        return self._write_result(self._request(
            "POST", "confModify", actor, data, mutation=True
        ), expected_id=int(old["confId"]))

    def modify(
        self, actor: Actor, old: dict[str, Any], *,
        title: str, start: datetime, minutes: int, parties: int,
        room_id: int | None = None,
    ) -> dict[str, Any]:
        """提交原会议的时间与资源修改，保留已知配置。"""
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
        return self._write_result(self._request(
            "POST", path, actor, data, mutation=True
        ), expected_id=int(old["confId"]))
