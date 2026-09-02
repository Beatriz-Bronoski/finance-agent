from pathlib import Path

from finance_agent.cli import main

ROOT = Path(__file__).resolve().parents[2]
PICPAY = ROOT / "samples" / "synthetic" / "picpay_demo_jul_ago_2026.csv"


def test_cli_displays_a_safe_persistence_execution(tmp_path: Path, capsys: object) -> None:
    database = tmp_path / "finance.db"
    arguments = [
        "ingest",
        str(PICPAY),
        "--registry",
        str(tmp_path / "registry.json"),
        "--persist",
        "--database",
        str(database),
    ]

    assert main(arguments) == 0
    first_output = capsys.readouterr().out  # type: ignore[attr-defined]
    assert "Persistência: stored" in first_output
    assert "Transações gravadas nesta execução: 11" in first_output
    assert "Total de transações no banco: 11" in first_output
    assert "MERCADO FICTICIO AURORA" not in first_output
    assert "48,75" not in first_output

    assert main(arguments) == 0
    second_output = capsys.readouterr().out  # type: ignore[attr-defined]
    assert "Persistência: already_imported" in second_output
    assert "Total de transações no banco: 11" in second_output


def test_database_commands_initialize_and_show_counts(tmp_path: Path, capsys: object) -> None:
    database = tmp_path / "finance.db"

    assert main(["db", "init", "--database", str(database)]) == 0
    initialized = capsys.readouterr().out  # type: ignore[attr-defined]
    assert "Versão do banco: 2" in initialized

    assert main(["db", "summary", "--database", str(database)]) == 0
    summary = capsys.readouterr().out  # type: ignore[attr-defined]
    assert "Transações: 0" in summary
    assert "Pendências abertas: 0" in summary


def test_cli_reports_unwritable_database_without_traceback(
    tmp_path: Path,
    capsys: object,
) -> None:
    parent_is_file = tmp_path / "not-a-directory"
    parent_is_file.write_text("blocked", encoding="utf-8")

    exit_code = main(
        [
            "db",
            "init",
            "--database",
            str(parent_is_file / "finance.db"),
        ]
    )
    output = capsys.readouterr().out  # type: ignore[attr-defined]

    assert exit_code == 1
    assert "Banco SQLite indisponível." in output
    assert "storage_initialize_failed" in output
