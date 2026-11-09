"""使用实际打包的 Schema 验证示例和错误边界。"""

import json
from copy import deepcopy
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator

from meeting_reservation import ContractValidationError, get_schema, validate_payload

EXAMPLES = Path(__file__).resolve().parents[1] / "examples"


def example(name: str) -> dict:
    """读取固定的契约示例，不重新实现解析逻辑。"""
    return json.loads((EXAMPLES / name).read_text(encoding="utf-8"))


@pytest.mark.parametrize("kind", ["intent", "request", "continue", "operation-query", "result"])
def test_json_schemas_are_valid(kind: str) -> None:
    """所有交付的 JSON Schema 必须符合 Draft 2020-12。"""
    Draft202012Validator.check_schema(get_schema(kind))


@pytest.mark.parametrize("file", sorted(EXAMPLES.glob("*.json")), ids=lambda f: f.name)
def test_examples_follow_real_contract(file: Path) -> None:
    """所有示例直接由正式生产校验入口验证。"""
    kind = file.name.rsplit(".", 2)[-2]
    validate_payload(kind, json.loads(file.read_text(encoding="utf-8")))


def test_create_allows_missing_business_fields() -> None:
    """合法的未补全语义输入不应被误认为已可创建。"""
    payload = example("create.intent.json")
    payload["meeting"]["start_at"] = None
    payload["meeting"]["room_query"] = None
    validate_payload("intent", payload)


def test_create_cannot_target_existing_meeting() -> None:
    """创建请求不能携带修改目标，以免错误覆盖已有会议。"""
    payload = example("create.intent.json")
    payload["target"] = {"meeting_id": "meeting_123", "search_text": None}
    with pytest.raises(ContractValidationError):
        validate_payload("intent", payload)


@pytest.mark.parametrize("extra", [{"untrusted_user_id": "admin"}, {"action": "DELETE"}])
def test_reject_unknown_or_illegal_intent(extra: dict) -> None:
    """模型输出非法动作或伪造身份字段必须直接拒绝。"""
    payload = example("create.intent.json")
    payload.update(extra)
    with pytest.raises(ContractValidationError):
        validate_payload("intent", payload)


def test_reject_shift_of_zero_minutes() -> None:
    """零分钟修改不应通过结构验证。"""
    payload = example("update-relative.intent.json")
    payload["update"]["time_shift_minutes"] = 0
    with pytest.raises(ContractValidationError):
        validate_payload("intent", payload)


def test_reject_naive_datetime() -> None:
    """会议时间必须含明确 UTC offset，不能依赖宿主时区。"""
    payload = example("create.intent.json")
    payload["meeting"]["start_at"] = "2026-11-05T14:00:00"
    with pytest.raises(ContractValidationError):
        validate_payload("intent", payload)


def test_reject_reversed_create_interval() -> None:
    """会议信息起止时间倒置时应拒绝，而不是把错误交给 MCP 写入。"""
    payload = example("create.intent.json")
    payload["meeting"]["start_at"] = "2026-11-05T17:00:00+08:00"
    with pytest.raises(ContractValidationError):
        validate_payload("intent", payload)


def test_reject_equal_create_interval() -> None:
    """开始与结束时间相等时必须拒绝。"""
    payload = example("create.intent.json")
    payload["meeting"]["end_at"] = payload["meeting"]["start_at"]
    with pytest.raises(ContractValidationError):
        validate_payload("intent", payload)


def test_reject_reversed_absolute_update_interval() -> None:
    """显式同时修改时间时也要检查两字段的顺序。"""
    payload = example("update-fields.intent.json")
    payload["update"]["changes"]["end_at"] = "2026-11-05T12:00:00+08:00"
    with pytest.raises(ContractValidationError):
        validate_payload("intent", payload)


def test_reject_empty_update() -> None:
    """没有时间平移且没有字段变化时，不允许提交空更新。"""
    payload = example("update-fields.intent.json")
    payload["update"]["changes"] = {}
    with pytest.raises(ContractValidationError):
        validate_payload("intent", payload)


def test_committed_requires_real_meeting_id() -> None:
    """不能让没有真实会议 ID 的结果被 ADP 当作预订成功。"""
    payload = example("committed.result.json")
    payload["meeting_id"] = None
    with pytest.raises(ContractValidationError):
        validate_payload("result", payload)


def test_pending_conflict_requires_revision_and_expiration() -> None:
    """有冲突的结果必须携带可安全恢复的持久化状态标识。"""
    payload = example("conflict.result.json")
    payload["pending_revision"] = None
    with pytest.raises(ContractValidationError):
        validate_payload("result", payload)
    payload = example("conflict.result.json")
    payload["expires_at"] = None
    with pytest.raises(ContractValidationError):
        validate_payload("result", payload)


def test_request_reuses_intent_schema() -> None:
    """MCP 请求中的意图必须引用同一份模型契约。"""
    payload = example("submit-create.request.json")
    payload["intent"]["action"] = "DELETE"
    with pytest.raises(ContractValidationError):
        validate_payload("request", payload)


def test_error_requires_machine_details() -> None:
    """明确失败必须含可供工作流判断的机器错误对象。"""
    payload = example("failed.result.json")
    payload["error"] = None
    with pytest.raises(ContractValidationError):
        validate_payload("result", payload)


def test_schema_mutation_does_not_change_registry() -> None:
    """外部修改 Schema 副本不得污染后续校验。"""
    schema = get_schema("intent")
    schema["properties"]["schema_version"]["const"] = "BROKEN"
    validate_payload("intent", deepcopy(example("create.intent.json")))


def test_time_comparison_uses_absolute_instants() -> None:
    """跨时区时间必须以实际瞬时比较，不能使用文本排序。"""
    payload = example("create.intent.json")
    payload["meeting"]["end_at"] = "2026-11-05T06:30:00+00:00"
    validate_payload("intent", payload)

    payload["meeting"]["end_at"] = "2026-11-05T05:59:00+00:00"
    with pytest.raises(ContractValidationError):
        validate_payload("intent", payload)


def test_incomplete_update_is_a_valid_extraction_not_a_write() -> None:
    """允许识别到 UPDATE 但字段尚缺失，完整性属于业务层判断。"""
    payload = example("update-relative.intent.json")
    payload["target"] = None
    payload["update"] = None
    validate_payload("intent", payload)


def test_operation_query_requires_a_stable_operation_id() -> None:
    """状态查询必须使用符合契约的操作标识，不能填普通对话文本。"""
    payload = example("operation-status.operation-query.json")
    payload["operation_id"] = "hello"
    with pytest.raises(ContractValidationError):
        validate_payload("operation-query", payload)
