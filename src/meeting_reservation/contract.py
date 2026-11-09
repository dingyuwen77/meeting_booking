"""统一加载 JSON Schema，并使用正式契约校验 ADP/MCP 消息。"""

import json
from copy import deepcopy
from datetime import datetime
from functools import lru_cache
from importlib import resources
from typing import Any

from jsonschema import Draft202012Validator, FormatChecker
from referencing import Registry, Resource

SCHEMA_FILES = {
    "intent": "meeting-intent.v1.schema.json",
    "request": "meeting-request.v1.schema.json",
    "continue": "meeting-continue.v1.schema.json",
    "operation-query": "meeting-operation-query.v1.schema.json",
    "result": "meeting-result.v1.schema.json",
}


class ContractValidationError(ValueError):
    """表示指定契约消息不符合机器 Schema 或跨字段语义约束。"""


@lru_cache(maxsize=1)
def _schemas() -> dict[str, dict[str, Any]]:
    """只从包内 JSON Schema 读取机器契约，避免模型与示例重复维护定义。"""
    folder = resources.files("meeting_reservation").joinpath("schemas")
    schemas = {}
    for kind, filename in SCHEMA_FILES.items():
        data = json.loads(folder.joinpath(filename).read_text(encoding="utf-8"))
        Draft202012Validator.check_schema(data)
        schemas[kind] = data
    return schemas


@lru_cache(maxsize=1)
def _registry() -> Registry:
    """在本地注册所有 Schema 的 URN，避免跨契约引用时访问网络。"""
    return Registry().with_resources(
        (schema["$id"], Resource.from_contents(schema)) for schema in _schemas().values()
    )


def get_schema(kind: str) -> dict[str, Any]:
    """按消息类型取得独立 Schema 副本，防止调用方修改缓存中的契约。"""
    if kind not in SCHEMA_FILES:
        raise ValueError(f"不支持的契约类型：{kind}")
    return deepcopy(_schemas()[kind])


def _check_time_order(start_at: str | None, end_at: str | None, path: str) -> None:
    """同时知道起止时间时按实际时区比较，不能只比较字符串。"""
    if start_at is None or end_at is None:
        return
    if datetime.fromisoformat(end_at) <= datetime.fromisoformat(start_at):
        raise ContractValidationError(f"{path}：结束时间必须晚于开始时间")


def _validate_intent_semantics(intent: dict[str, Any]) -> None:
    """补充 JSON Schema 不擅长表达的跨字段时间不变量。"""
    meeting = intent["meeting"]
    if meeting is not None:
        _check_time_order(meeting["start_at"], meeting["end_at"], "$.meeting")
    update = intent["update"]
    if update is not None:
        # JSON Schema 已约束偏移与绝对时间互斥；此处只检查时间先后关系。
        changes = update["changes"]
        _check_time_order(changes.get("start_at"), changes.get("end_at"), "$.update.changes")


def validate_payload(kind: str, payload: Any) -> None:
    """验证机器 Schema 与适用的跨字段不变量，不判断真实会议资源是否可用。"""
    if kind not in SCHEMA_FILES:
        raise ValueError(f"不支持的契约类型：{kind}")
    validator = Draft202012Validator(
        _schemas()[kind], registry=_registry(), format_checker=FormatChecker()
    )
    errors = sorted(
        validator.iter_errors(payload),
        key=lambda e: ("/".join(map(str, e.absolute_path)), e.message),
    )
    if errors:
        error = errors[0]
        path = "$" + "".join(f"[{part!r}]" for part in error.absolute_path)
        raise ContractValidationError(f"{kind} 契约校验失败：{path}：{error.message}")

    if kind == "intent":
        _validate_intent_semantics(payload)
    elif kind == "request":
        _validate_intent_semantics(payload["intent"])
