"""统一 UPDATE 契约行为：支持时间平移与字段变化组合，拒绝歧义写入。"""

import json
from copy import deepcopy
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator

from meeting_reservation import ContractValidationError, get_schema, validate_payload

ROOT = Path(__file__).resolve().parents[1]


def update_intent(shift: int | None, changes: dict) -> dict:
    """构造合法上下文，仅替换本次需要测试的 update 结构。"""
    payload = json.loads((ROOT / "examples" / "update-relative.intent.json").read_text("utf-8"))
    payload["update"] = {"time_shift_minutes": shift, "changes": deepcopy(changes)}
    return payload


@pytest.mark.parametrize(
    ("shift", "changes"),
    [
        (60, {}),
        (-30, {}),
        (None, {"room_query": "A302"}),
        (None, {"start_at": "2026-11-05T15:00:00+08:00", "end_at": "2026-11-05T16:00:00+08:00"}),
        (60, {"room_query": "A302"}),
        (-30, {"room_query": "A302", "attendee_queries": ["张三"]}),
        (60, {"description": None}),
    ],
)
def test_valid_update_is_single_composable_shape(shift: int | None, changes: dict) -> None:
    """相对平移、字段更新和可组合修改共用同一种 UPDATE 请求格式。"""
    intent = update_intent(shift, changes)
    validate_payload("intent", intent)
    assert Draft202012Validator(get_schema("intent")).is_valid(intent)


@pytest.mark.parametrize(
    ("shift", "changes"),
    [
        (None, {}),
        (0, {}),
        (0, {"room_query": "A302"}),
        (True, {}),
        (60, {"start_at": "2026-11-05T14:00:00+08:00"}),
        (60, {"end_at": "2026-11-05T15:00:00+08:00"}),
        (-30, {"room_query": "A302", "start_at": "2026-11-05T15:00:00+08:00"}),
        (None, {"start_at": "2026-11-05T17:00:00+08:00", "end_at": "2026-11-05T16:00:00+08:00"}),
    ],
)
def test_reject_empty_ambiguous_or_invalid_update(shift: int | None, changes: dict) -> None:
    """空更新、零偏移及偏移与绝对时间互斥要被机器契约可靠拒绝。"""
    intent = update_intent(shift, changes)
    with pytest.raises(ContractValidationError):
        validate_payload("intent", intent)


@pytest.mark.parametrize(
    "update",
    [
        {"mode": "SHIFT", "minutes": 60},
        {"mode": "PATCH", "changes": {"room_query": "A302"}},
        {"time_shift_minutes": 60},
        {"changes": {"room_query": "A302"}},
        {"time_shift_minutes": 60, "changes": {}, "mode": "SHIFT"},
    ],
)
def test_reject_old_modes_missing_fields_or_unknown_keys(update: dict) -> None:
    """新候选契约不默许旧双模式及缺失字段造成的语义漂移。"""
    intent = update_intent(60, {})
    intent["update"] = update
    with pytest.raises(ContractValidationError):
        validate_payload("intent", intent)


def test_request_reuses_unified_update_contract() -> None:
    """外层 MCP submit 请求应通过同一个嵌套意图 Schema。"""
    request = {
        "schema_version": "meeting.request.v1",
        "operation_id": "op_example_update_001",
        "intent": update_intent(60, {"room_query": "A302"}),
    }
    validate_payload("request", request)
    request["intent"]["update"]["changes"]["end_at"] = "2026-11-05T16:00:00+08:00"
    with pytest.raises(ContractValidationError):
        validate_payload("request", request)


def test_incomplete_update_remains_valid_semantic_extraction() -> None:
    """尚未识别出修改指令时可用 null 表示缺参，不能伪造已可写入。"""
    intent = update_intent(60, {})
    intent["target"] = None
    intent["update"] = None
    validate_payload("intent", intent)
