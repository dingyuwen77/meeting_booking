"""验证受信网关签名的企微成员身份；模型传入的 ID 永远不是身份凭据。"""

import base64
import hashlib
import hmac
import json
import re
import time
from dataclasses import dataclass
from typing import Mapping

from .settings import Settings

_USER_ID = re.compile(r"^[A-Za-z0-9_@.\-]{1,128}$")


class IdentityError(ValueError):
    """请求没有可验证的企业微信成员身份。"""


@dataclass(frozen=True)
class Actor:
    corp_id: str
    user_id: str
    user_name: str

    @property
    def key(self) -> str:
        return f"{self.corp_id}:{self.user_id}"


def verify_identity(
    headers: Mapping[str, str], settings: Settings, now: int | None = None
) -> Actor:
    """签名数据为 base64url(JSON)，HMAC 对未解码的 base64url 文本签名。

    只有持有共享密钥的可信网关可以签名；请求 Header 自身并不可信。
    签名在每个 tools/call 请求内校验，拒绝缺失、过期及跨企业数据。
    """
    if len(settings.identity_secret) < 32 or not settings.corp_id:
        raise IdentityError("身份认证未配置")
    fields = {str(k).lower(): str(v) for k, v in headers.items()}
    encoded = fields.get("x-meeting-actor", "")
    signature = fields.get("x-meeting-signature", "")
    if (
        not encoded or len(encoded) > 2048
        or re.fullmatch(r"[A-Za-z0-9_-]+", encoded) is None
        or re.fullmatch(r"[A-Fa-f0-9]{64}", signature) is None
    ):
        raise IdentityError("缺少有效身份签名")
    expected = hmac.new(
        settings.identity_secret.encode("utf-8"), encoded.encode("ascii"), hashlib.sha256
    ).hexdigest()
    if not hmac.compare_digest(expected, signature.lower()):
        raise IdentityError("身份签名不正确")
    try:
        raw = base64.urlsafe_b64decode(encoded + "=" * (-len(encoded) % 4))
        claims = json.loads(raw)
        if not isinstance(claims, dict) or set(claims) != {
            "corp_id", "user_id", "user_name", "iat"
        }:
            raise ValueError("身份声明字段非法")
        issued_at = claims["iat"]
        if type(issued_at) is not int:
            raise ValueError("签名时间戳必须是整数")
        reference = int(time.time()) if now is None else now
        if abs(reference - issued_at) > 90:
            raise ValueError("身份签名已过期或尚未生效")
        if claims["corp_id"] != settings.corp_id:
            raise ValueError("企业身份不匹配")
        if not isinstance(claims["user_id"], str) or not _USER_ID.fullmatch(
            claims["user_id"]
        ):
            raise ValueError("用户标识格式不正确")
        name = claims["user_name"]
        if not isinstance(name, str) or not name.strip() or len(name) > 128:
            raise ValueError("成员名称缺失")
        return Actor(claims["corp_id"], claims["user_id"], name)
    except (ValueError, TypeError, UnicodeError, KeyError, base64.binascii.Error) as exc:
        raise IdentityError("无效的企业成员身份声明") from exc


def sign_identity(actor: Actor, secret: str, issued_at: int) -> dict[str, str]:
    """供可信上游网关使用的签名实现；不能由 ADP 大模型或浏览器调用。"""
    claims = {
        "corp_id": actor.corp_id,
        "user_id": actor.user_id,
        "user_name": actor.user_name,
        "iat": issued_at,
    }
    encoded = base64.urlsafe_b64encode(
        json.dumps(claims, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    ).decode("ascii").rstrip("=")
    signature = hmac.new(
        secret.encode("utf-8"), encoded.encode("ascii"), hashlib.sha256
    ).hexdigest()
    return {"X-Meeting-Actor": encoded, "X-Meeting-Signature": signature}
