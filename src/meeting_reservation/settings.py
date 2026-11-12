"""服务端配置：所有真实凭据和写入开关均来自运行环境。"""

import os
from dataclasses import dataclass, field


@dataclass(frozen=True)
class IdentityProbeSettings:
    """临时参数探针的独立配置，不读取会议或供应商配置。"""

    enabled: bool = False
    key: str = field(default="", repr=False)

    @classmethod
    def from_env(cls) -> "IdentityProbeSettings":
        """只在显式开启时要求可安全放入 Header 的随机密钥。"""
        enabled = os.getenv("MEETING_IDENTITY_PROBE_ENABLED", "").lower() == "true"
        key = os.getenv("MEETING_IDENTITY_PROBE_KEY", "") if enabled else ""
        if enabled and (len(key) < 32 or not all("!" <= char <= "~" for char in key)):
            raise ValueError("MEETING_IDENTITY_PROBE_KEY 必须为至少 32 个非空白可打印 ASCII 字符")
        return cls(enabled=enabled, key=key)


@dataclass(frozen=True)
class Settings:
    site_sign: str
    api_key: str
    corp_id: str
    identity_secret: str
    db_path: str
    default_parties: int
    write_enabled: bool
    base_url: str
    timeout_seconds: float

    @classmethod
    def from_env(cls) -> "Settings":
        """读取并校验服务端环境配置，不自动加载本地密钥文件。"""
        raw_parties = os.getenv("MEETING_DEFAULT_PARTIES", "25")
        raw_timeout = os.getenv("MEETING_HTTP_TIMEOUT", "10")
        raw_url = os.getenv(
            "MEETING_BIZVIDEO_BASE_URL", "https://apinext.bizvideo.cn/openapi/v1"
        ).rstrip("/")
        if not raw_url.startswith("https://") or "@" in raw_url:
            raise ValueError("会畅 OpenAPI 端点必须是可信 HTTPS 地址")
        parties = int(raw_parties)
        timeout = float(raw_timeout)
        if parties < 1 or timeout <= 0:
            raise ValueError("会议方数与请求超时时长必须大于零")
        return cls(
            site_sign=os.getenv("MEETING_SITE_SIGN", ""),
            api_key=os.getenv("MEETING_API_KEY", ""),
            corp_id=os.getenv("MEETING_CORP_ID", ""),
            identity_secret=os.getenv("MEETING_IDENTITY_SECRET", ""),
            db_path=os.getenv("MEETING_DB_PATH", "./data/meeting_booking.sqlite3"),
            default_parties=parties,
            write_enabled=os.getenv("MEETING_WRITE_ENABLED", "").lower() == "true",
            base_url=raw_url,
            timeout_seconds=timeout,
        )

    def require_provider(self) -> None:
        """在供应商调用前要求站点和密钥均已配置。"""
        if not self.site_sign or not self.api_key:
            raise ValueError("缺少 MEETING_SITE_SIGN 或 MEETING_API_KEY")
