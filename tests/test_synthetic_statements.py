import csv
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SAMPLES = ROOT / "samples" / "synthetic"


def test_picpay_fixture_has_expected_structure_and_edge_cases() -> None:
    path = SAMPLES / "picpay_demo_jul_ago_2026.csv"
    with path.open(encoding="utf-8", newline="") as stream:
        rows = list(csv.DictReader(stream))

    assert list(rows[0]) == [
        "data",
        "hora",
        "tipo",
        "origem / destino",
        "valor",
        "forma de pagamento",
    ]
    assert len(rows) == 12
    assert any(row["valor"].startswith("+R$") for row in rows)
    assert any(row["valor"].startswith("−R$") for row in rows)
    fingerprints = [tuple(row.items()) for row in rows]
    assert len(fingerprints) > len(set(fingerprints))


def test_bradesco_fixture_preserves_structural_edge_cases() -> None:
    path = SAMPLES / "bradesco_demo_jul_ago_2026.csv"
    lines = path.read_text(encoding="utf-8").splitlines()
    dated = [line for line in lines if len(line) >= 10 and line[2] == "/" and line[5] == "/"]

    assert len(dated) == 12
    assert any(";0;" in line for line in dated)
    assert any(";123456789;" in line for line in dated)
    assert any(len(line.split(";")) > 6 for line in dated)

