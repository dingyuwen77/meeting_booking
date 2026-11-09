"""统一入口：供开发者在连接 ADP 前验证 JSON 文件与全部示例。"""

import argparse
import json
import sys
from collections.abc import Sequence
from pathlib import Path

from .contract import SCHEMA_FILES, validate_payload


def _validate_file(kind: str, filepath: Path) -> None:
    """使用生产契约验证单个文件，不维护第二套 Schema。"""
    content = json.loads(filepath.read_text(encoding="utf-8-sig"))
    validate_payload(kind, content)


def _validate_examples(folder: Path) -> int:
    """批量校验示例目录，文件名后缀决定真实契约类型。"""
    paths = sorted(folder.glob("*.json"))
    if not paths:
        print(f"未发现 JSON 示例：{folder}", file=sys.stderr)
        return 2
    for path in paths:
        kind = path.name.rsplit(".", 2)[-2]
        if kind not in SCHEMA_FILES:
            print(f"示例文件缺少已知契约后缀：{path}", file=sys.stderr)
            return 2
        try:
            _validate_file(kind, path)
        except (OSError, ValueError, json.JSONDecodeError) as error:
            print(f"无效示例：{path}：{error}", file=sys.stderr)
            return 2
    print(f"全部 {len(paths)} 份示例通过契约校验")
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    """解析本地 CLI 参数，成功返回 0，输入/校验错误返回 2。"""
    parser = argparse.ArgumentParser(description="ADP 会议 MCP 契约校验工具")
    subparsers = parser.add_subparsers(dest="command", required=True)
    single = subparsers.add_parser("validate", help="校验单个 JSON 消息")
    single.add_argument("kind", choices=tuple(SCHEMA_FILES))
    single.add_argument("path", type=Path)
    examples = subparsers.add_parser("validate-examples", help="验证全部固定示例")
    examples.add_argument("--dir", type=Path, default=Path("examples"))
    args = parser.parse_args(argv)

    if args.command == "validate-examples":
        return _validate_examples(args.dir)
    try:
        _validate_file(args.kind, args.path)
    except (OSError, ValueError, json.JSONDecodeError) as error:
        print(f"校验失败：{error}", file=sys.stderr)
        return 2
    print(f"校验成功：{args.kind} {args.path}")
    return 0
