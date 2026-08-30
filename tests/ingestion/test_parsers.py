from pathlib import Path

from finance_agent.application import ingest_file, safe_summary_lines
from finance_agent.ingestion.models import DetectionStatus, IngestionStatus
from finance_agent.ingestion.parsers.picpay import PicPayCsvParser


ROOT = Path(__file__).resolve().parents[2]
SAMPLES = ROOT / "samples" / "synthetic"


def test_picpay_ingestion_accounts_for_duplicates(tmp_path: Path) -> None:
    outcome = ingest_file(
        SAMPLES / "picpay_demo_jul_ago_2026.csv",
        registry_path=tmp_path / "registry.json",
    )

    assert outcome.summary.status == IngestionStatus.COMPLETED_WITH_ISSUES
    assert outcome.summary.records_read == 12
    assert outcome.summary.transactions_created == 11
    assert outcome.summary.pending_created == 0
    assert outcome.summary.duplicates_found == 1
    assert outcome.summary.records_rejected == 0
    assert any(transaction.amount_minor == 25000 for transaction in outcome.transactions)
    assert any(transaction.amount_minor == -4875 for transaction in outcome.transactions)


def test_detection_depends_on_content_not_filename(tmp_path: Path) -> None:
    renamed = tmp_path / "arquivo_sem_nome_do_banco.csv"
    renamed.write_bytes((SAMPLES / "picpay_demo_jul_ago_2026.csv").read_bytes())

    outcome = ingest_file(renamed, registry_path=tmp_path / "registry.json")

    assert outcome.summary.format_id == "picpay_csv_v1"
    assert outcome.summary.institution == "PicPay"


def test_bradesco_parser_preserves_variable_ids_and_split_description(tmp_path: Path) -> None:
    outcome = ingest_file(
        SAMPLES / "bradesco_demo_jul_ago_2026.csv",
        registry_path=tmp_path / "registry.json",
    )

    assert outcome.summary.records_read == 12
    assert outcome.summary.transactions_created == 11
    assert outcome.summary.records_rejected == 1
    split = next(item for item in outcome.transactions if item.external_id == "84521")
    assert split.description_normalized == "COMPRA LOJA FICTICIA SOL"
    assert split.amount_minor == -8000
    assert split.balance_minor == 167000
    assert any(item.external_id == "0" for item in outcome.transactions)
    assert any(item.external_id == "123456789" for item in outcome.transactions)


def test_generic_csv_requires_approval_then_is_recognized(tmp_path: Path) -> None:
    csv_path = tmp_path / "new_bank.csv"
    csv_path.write_text(
        "Data Movimento;Detalhes;Montante;Natureza\n"
        "10/08/2026;LOJA DEMO;12,50;Pagamento\n"
        "11/08/2026;PESSOA DEMO;30,00;Credito\n",
        encoding="utf-8",
    )
    registry = tmp_path / "private" / "mappings.json"

    first = ingest_file(csv_path, registry_path=registry)
    assert first.summary.status == IngestionStatus.BLOCKED
    assert first.summary.detection_status == DetectionStatus.GENERIC
    assert first.suggested_mapping is not None

    approved = ingest_file(
        csv_path,
        registry_path=registry,
        approve_generic_as="Banco Novo",
        generic_currency="BRL",
        generic_date_order="dmy",
    )
    assert approved.summary.detection_status == DetectionStatus.LEARNED
    assert approved.summary.transactions_created == 2
    assert sorted(item.amount_minor for item in approved.transactions) == [-1250, 3000]

    recognized = ingest_file(csv_path, registry_path=registry)
    assert recognized.summary.detection_status == DetectionStatus.LEARNED
    assert recognized.summary.transactions_created == 2


def test_known_schema_change_blocks_processing(tmp_path: Path) -> None:
    changed = tmp_path / "changed_picpay.csv"
    changed.write_text(
        "data,hora,tipo,valor,forma de pagamento\n"
        '2026-08-10,08:00:00,Pagamento,"-R$ 10,00",Saldo PicPay\n',
        encoding="utf-8",
    )

    outcome = ingest_file(changed, registry_path=tmp_path / "registry.json")

    assert outcome.summary.status == IngestionStatus.BLOCKED
    assert outcome.summary.format_id == "picpay_csv_v1"
    assert "missing_column" in outcome.summary.issue_counts
    assert outcome.transactions == []


def test_invalid_minimum_values_become_pending(tmp_path: Path) -> None:
    malformed = tmp_path / "malformed_picpay.csv"
    malformed.write_text(
        "data,hora,tipo,origem / destino,valor,forma de pagamento\n"
        'data-invalida,08:00:00,Pagamento,LOJA DEMO,"R$ XX",Saldo PicPay\n',
        encoding="utf-8",
    )

    outcome = ingest_file(malformed, registry_path=tmp_path / "registry.json")

    assert outcome.summary.pending_created == 1
    assert outcome.summary.transactions_created == 0
    assert "invalid_transaction_date" in outcome.summary.issue_counts
    assert "invalid_amount" in outcome.summary.issue_counts


def test_generic_positive_amount_without_direction_remains_pending(tmp_path: Path) -> None:
    ambiguous = tmp_path / "ambiguous.csv"
    ambiguous.write_text(
        "Date,Description,Amount\n2026-08-10,STORE DEMO,10.00\n",
        encoding="utf-8",
    )

    outcome = ingest_file(
        ambiguous,
        registry_path=tmp_path / "registry.json",
        approve_generic_as="Generic Bank",
        generic_currency="USD",
    )

    assert outcome.summary.pending_created == 1
    assert outcome.summary.transactions_created == 0
    assert "ambiguous_amount_direction" in outcome.summary.issue_counts


def test_new_format_requires_currency_and_preserves_foreign_currency(tmp_path: Path) -> None:
    foreign = tmp_path / "foreign.csv"
    foreign.write_text(
        "Date,Description,Amount,Direction\n"
        "2026-08-13,STORE DEMO,10.00,Debit\n",
        encoding="utf-8",
    )
    registry = tmp_path / "registry.json"

    missing_currency = ingest_file(
        foreign,
        registry_path=registry,
        approve_generic_as="Foreign Bank",
    )
    assert missing_currency.summary.status == IngestionStatus.BLOCKED
    assert "missing_currency" in missing_currency.summary.issue_counts

    approved = ingest_file(
        foreign,
        registry_path=registry,
        approve_generic_as="Foreign Bank",
        generic_currency="USD",
        generic_date_order="ymd",
    )
    assert approved.summary.transactions_created == 1
    assert approved.transactions[0].currency == "USD"


def test_safe_summary_never_exposes_transaction_values(tmp_path: Path) -> None:
    outcome = ingest_file(
        SAMPLES / "picpay_demo_jul_ago_2026.csv",
        registry_path=tmp_path / "registry.json",
    )
    rendered = "\n".join(safe_summary_lines(outcome))

    assert "MERCADO FICTICIO AURORA" not in rendered
    assert "48,75" not in rendered
    assert "+R$" not in rendered


def test_unsupported_extension_and_corrupt_registry_are_blocked(tmp_path: Path) -> None:
    unsupported = ingest_file(
        SAMPLES / "bradesco_demo_jul_ago_2026.pdf",
        registry_path=tmp_path / "registry.json",
    )
    assert unsupported.summary.status == IngestionStatus.BLOCKED
    assert "unsupported_file_type" in unsupported.summary.issue_counts

    registry = tmp_path / "registry.json"
    registry.write_text("not-json", encoding="utf-8")
    blocked = ingest_file(
        SAMPLES / "picpay_demo_jul_ago_2026.csv",
        registry_path=registry,
    )
    assert blocked.summary.status == IngestionStatus.BLOCKED
    assert "registry_invalid" in blocked.summary.issue_counts


def test_missing_csv_is_reported_without_raising(tmp_path: Path) -> None:
    outcome = ingest_file(
        tmp_path / "missing.csv",
        registry_path=tmp_path / "registry.json",
    )

    assert outcome.summary.status == IngestionStatus.BLOCKED
    assert "unreadable_file" in outcome.summary.issue_counts


def test_file_change_during_processing_discards_result(
    tmp_path: Path,
    monkeypatch: object,
) -> None:
    changing = tmp_path / "changing.csv"
    changing.write_bytes((SAMPLES / "picpay_demo_jul_ago_2026.csv").read_bytes())
    original_parse = PicPayCsvParser.parse

    def parse_and_change(
        parser: PicPayCsvParser,
        path: Path,
        profile: object,
        spec: object,
    ) -> object:
        result = original_parse(parser, path, profile, spec)  # type: ignore[arg-type]
        path.write_bytes(path.read_bytes() + b"\n")
        return result

    monkeypatch.setattr(PicPayCsvParser, "parse", parse_and_change)  # type: ignore[attr-defined]
    outcome = ingest_file(changing, registry_path=tmp_path / "registry.json")

    assert outcome.summary.status == IngestionStatus.FAILED
    assert "file_changed_during_read" in outcome.summary.issue_counts
    assert outcome.transactions == []
