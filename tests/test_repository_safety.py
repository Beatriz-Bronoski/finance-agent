from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SYNTHETIC = ROOT / "samples" / "synthetic"
FORBIDDEN_SUFFIXES = {".xlsx", ".xls", ".ofx", ".qif", ".db", ".sqlite", ".sqlite3", ".ipynb"}
ALLOWED_DATA_FILES = {
    SYNTHETIC / "picpay_demo_jul_ago_2026.csv",
    SYNTHETIC / "bradesco_demo_jul_ago_2026.csv",
    SYNTHETIC / "bradesco_demo_jul_ago_2026.pdf",
}


def test_no_forbidden_financial_artifacts_are_tracked() -> None:
    violations = [
        path.relative_to(ROOT)
        for path in ROOT.rglob("*")
        if path.is_file() and path.suffix.lower() in FORBIDDEN_SUFFIXES
    ]
    assert violations == []


def test_data_files_are_restricted_to_synthetic_fixtures() -> None:
    discovered = {
        path
        for path in ROOT.rglob("*")
        if path.is_file() and path.suffix.lower() in {".csv", ".pdf"}
    }
    assert discovered == ALLOWED_DATA_FILES


def test_synthetic_directory_contains_prominent_disclaimer() -> None:
    disclaimer = (SYNTHETIC / "README.md").read_text(encoding="utf-8")
    assert "DADOS TOTALMENTE FICTICIOS" in disclaimer

