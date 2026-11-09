"""腾讯 ADP 与会议 MCP 之间的版本化契约及本地校验工具。"""

from .contract import ContractValidationError, get_schema, validate_payload

__all__ = ["ContractValidationError", "get_schema", "validate_payload"]
