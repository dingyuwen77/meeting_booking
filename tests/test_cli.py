"""从 CLI 正式入口确认示例与错误码行为。"""

from pathlib import Path

from meeting_reservation.cli import main

ROOT = Path(__file__).resolve().parents[1]


def test_cli_validates_all_examples(capsys) -> None:
    """示例批量校验必须真实完成并报告条数。"""
    code = main(["validate-examples", "--dir", str(ROOT / "examples")])
    output = capsys.readouterr()
    assert code == 0
    expected = len(list((ROOT / "examples").glob("*.json")))
    assert f"{expected} 份示例" in output.out


def test_cli_validates_single_file(capsys) -> None:
    """CLI 应能按契约类型校验单个文件。"""
    code = main(["validate", "intent", str(ROOT / "examples" / "create.intent.json")])
    output = capsys.readouterr()
    assert code == 0
    assert "校验成功" in output.out


def test_cli_reports_invalid_file(tmp_path, capsys) -> None:
    """不合法的 JSON 返回非零码，避免误报验证成功。"""
    bad = tmp_path / "wrong.json"
    bad.write_text('{"schema_version":"unknown"}', encoding="utf-8")
    code = main(["validate", "intent", str(bad)])
    output = capsys.readouterr()
    assert code == 2
    assert "校验失败" in output.err


def test_cli_reports_empty_example_dir(tmp_path, capsys) -> None:
    """缺少示例时不能假装批量校验通过。"""
    code = main(["validate-examples", "--dir", str(tmp_path)])
    output = capsys.readouterr()
    assert code == 2
    assert "未发现" in output.err
