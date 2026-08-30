import json
from pathlib import Path

from finance_agent.cli import main


ROOT = Path(__file__).resolve().parents[2]
PICPAY = ROOT / "samples" / "synthetic" / "picpay_demo_jul_ago_2026.csv"


def test_cli_prints_only_safe_summary(tmp_path: Path, capsys: object) -> None:
    exit_code = main(
        ["ingest", str(PICPAY), "--registry", str(tmp_path / "registry.json")]
    )
    output = capsys.readouterr().out  # type: ignore[attr-defined]

    assert exit_code == 0
    assert "Registros lidos: 12" in output
    assert "MERCADO FICTICIO AURORA" not in output


def test_cli_json_contains_summary_not_transactions(tmp_path: Path, capsys: object) -> None:
    exit_code = main(
        [
            "ingest",
            str(PICPAY),
            "--registry",
            str(tmp_path / "registry.json"),
            "--json",
        ]
    )
    output = capsys.readouterr().out  # type: ignore[attr-defined]
    payload = json.loads(output)

    assert exit_code == 0
    assert payload["records_read"] == 12
    assert "transactions" not in payload
    assert "pending" not in payload
