from pathlib import Path

import pytest

from finance_agent.domain.enums import IssueSeverity
from finance_agent.ingestion.models import CsvSchemaProfile, DetectionStatus
from finance_agent.ingestion.registry import MappingRegistry, RegistryError
from finance_agent.ingestion.schema import (
    FormatDetector,
    SchemaDriftDetector,
    SchemaProfiler,
    builtin_format_specs,
    suggest_column_mapping,
)


ROOT = Path(__file__).resolve().parents[2]
SAMPLES = ROOT / "samples" / "synthetic"


def test_profiler_finds_headers_delimiters_and_irregular_rows() -> None:
    profiler = SchemaProfiler()
    picpay = profiler.profile(SAMPLES / "picpay_demo_jul_ago_2026.csv")
    bradesco = profiler.profile(SAMPLES / "bradesco_demo_jul_ago_2026.csv")

    assert picpay.delimiter == ","
    assert picpay.header_row_number == 1
    assert picpay.columns[:3] == ("data", "hora", "tipo")
    assert picpay.row_count == 12
    assert picpay.irregular_row_count == 0

    assert bradesco.delimiter == ";"
    assert bradesco.header_row_number == 3
    assert bradesco.columns == (
        "data",
        "historico",
        "docto",
        "credito",
        "debito",
        "saldo",
    )
    assert bradesco.row_count == 12
    assert bradesco.irregular_row_count == 1


def test_detector_selects_both_known_formats() -> None:
    profiler = SchemaProfiler()
    detector = FormatDetector()

    picpay = detector.detect(profiler.profile(SAMPLES / "picpay_demo_jul_ago_2026.csv"))
    bradesco = detector.detect(
        profiler.profile(SAMPLES / "bradesco_demo_jul_ago_2026.csv")
    )

    assert picpay.status == DetectionStatus.KNOWN
    assert picpay.selected_spec is not None
    assert picpay.selected_spec.parser_id == "picpay_csv"
    assert bradesco.status == DetectionStatus.KNOWN
    assert bradesco.selected_spec is not None
    assert bradesco.selected_spec.parser_id == "bradesco_csv"


def test_detector_blocks_equally_likely_formats() -> None:
    profile = SchemaProfiler().profile(SAMPLES / "picpay_demo_jul_ago_2026.csv")
    builtin = builtin_format_specs()[0]
    duplicate = builtin.model_copy(
        update={
            "format_id": "learned_duplicate",
            "institution": "Formato Duplicado",
            "parser_id": "generic_csv",
            "learned": True,
        }
    )

    result = FormatDetector((duplicate,)).detect(profile)

    assert result.status == DetectionStatus.AMBIGUOUS
    assert result.selected_spec is None


def test_schema_drift_blocks_missing_minimum_and_warns_new_columns() -> None:
    spec = builtin_format_specs()[0]
    changed = CsvSchemaProfile(
        delimiter=",",
        encoding="utf-8-sig",
        header_row_number=1,
        columns=("data", "hora", "tipo", "valor", "forma de pagamento", "novo campo"),
        row_count=1,
        irregular_row_count=0,
        signature="a" * 64,
        source_file_hash="b" * 64,
    )

    drift = SchemaDriftDetector().compare(changed, spec)

    assert drift.has_drift
    assert drift.is_breaking
    assert any(change.severity == IssueSeverity.BLOCKING for change in drift.changes)
    assert any("novo campo" in change.fields for change in drift.changes)


def test_generic_mapping_can_be_learned_without_saving_rows(tmp_path: Path) -> None:
    csv_path = tmp_path / "new_bank.csv"
    csv_path.write_text(
        "Data Movimento;Detalhes;Montante;Natureza\n"
        "10/08/2026;LOJA DEMO;12,50;Pagamento\n",
        encoding="utf-8",
    )
    profile = SchemaProfiler().profile(csv_path)
    suggestion = suggest_column_mapping(profile)

    assert suggestion.mapping.is_complete
    assert suggestion.mapping.transaction_date == "data movimento"
    assert suggestion.mapping.description == "detalhes"
    assert suggestion.mapping.amount == "montante"

    registry_path = tmp_path / "private" / "mappings.json"
    registry = MappingRegistry(registry_path)
    learned = registry.learn(profile, suggestion.mapping, "Banco Novo", "BRL", "dmy")
    reloaded = registry.list_specs()

    assert learned.learned
    assert len(reloaded) == 1
    assert reloaded[0].mapping == suggestion.mapping
    saved = registry_path.read_text(encoding="utf-8")
    assert "LOJA DEMO" not in saved
    assert "12,50" not in saved

    with pytest.raises(RegistryError):
        registry.learn(profile, suggestion.mapping, "Nome\nInseguro", "BRL", "dmy")
    with pytest.raises(RegistryError):
        registry.learn(profile, suggestion.mapping, "Banco Novo", "BRL", "invalid")


def test_profiler_supports_cp1252_and_enforces_size_limit(tmp_path: Path) -> None:
    cp1252_file = tmp_path / "legacy.csv"
    cp1252_file.write_bytes(
        "Data;Descrição;Valor\n10/08/2026;Farmácia;10,00\n".encode("cp1252")
    )
    profile = SchemaProfiler().profile(cp1252_file)

    assert profile.encoding == "cp1252"
    assert profile.columns == ("data", "descricao", "valor")

    too_large = tmp_path / "too_large.csv"
    too_large.write_text("Data,Descrição,Valor\n", encoding="utf-8")
    try:
        SchemaProfiler(max_file_bytes=5).profile(too_large)
    except ValueError as error:
        assert getattr(error, "code").value == "file_too_large"
    else:
        raise AssertionError("arquivo acima do limite deveria ser bloqueado")
