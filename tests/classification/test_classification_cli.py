from pathlib import Path

from finance_agent.application import ingest_and_persist
from finance_agent.cli import main
from finance_agent.persistence.classification_repository import SQLiteClassificationRepository

ROOT = Path(__file__).resolve().parents[2]
PICPAY = ROOT / "samples" / "synthetic" / "picpay_demo_jul_ago_2026.csv"


def test_classification_cli_has_safe_visible_flow(tmp_path: Path, capsys: object) -> None:
    database = tmp_path / "finance.db"
    ingest_and_persist(
        PICPAY,
        database_path=database,
        registry_path=tmp_path / "registry.json",
    )

    assert main(["categories", "add", "Alimentação", "--database", str(database)]) == 0
    capsys.readouterr()  # type: ignore[attr-defined]
    assert main(["classify", "run", "--database", str(database)]) == 0
    run_output = capsys.readouterr().out  # type: ignore[attr-defined]
    assert "Transações examinadas: 11" in run_output
    assert "Marcadas para revisão: 11" in run_output
    assert "MERCADO FICTICIO AURORA" not in run_output
    assert "48,75" not in run_output

    repository = SQLiteClassificationRepository(database)
    transactions, _ = repository.list_transactions_for_classification()
    transaction = transactions[0]
    arguments = [
        "classify",
        "correct",
        str(transaction.id),
        "--nature",
        "despesa",
        "--category",
        "Alimentação",
        "--remember",
        "--database",
        str(database),
    ]
    assert main(arguments) == 0
    correction_output = capsys.readouterr().out  # type: ignore[attr-defined]
    assert "Classificação confirmada pela usuária." in correction_output
    assert "Regra lembrada: sim" in correction_output
    assert transaction.description_normalized not in correction_output


def test_cli_rejects_expense_without_category_safely(tmp_path: Path, capsys: object) -> None:
    database = tmp_path / "finance.db"
    ingest_and_persist(
        PICPAY,
        database_path=database,
        registry_path=tmp_path / "registry.json",
    )
    repository = SQLiteClassificationRepository(database)
    transactions, _ = repository.list_transactions_for_classification()
    transaction = transactions[0]

    result = main(
        [
            "classify",
            "correct",
            str(transaction.id),
            "--nature",
            "despesa",
            "--database",
            str(database),
        ]
    )
    output = capsys.readouterr().out  # type: ignore[attr-defined]

    assert result == 1
    assert "Classificação indisponível." in output
    assert "expense_or_income_requires_active_category" in output
    assert transaction.description_normalized not in output
