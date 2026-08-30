import ast
from collections import Counter
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
SOURCE = ROOT / "src" / "finance_agent"


def test_every_public_function_has_a_real_call_site() -> None:
    source_files = list(SOURCE.rglob("*.py"))
    all_files = [*source_files, *ROOT.joinpath("tests").rglob("*.py")]
    public_functions: dict[str, Path] = {}
    references: Counter[str] = Counter()

    for path in source_files:
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in tree.body:
            is_function = isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
            if is_function and not node.name.startswith("_"):
                public_functions[node.name] = path

    for path in all_files:
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.Name) and isinstance(node.ctx, ast.Load):
                references[node.id] += 1

    unused = {
        name: str(path.relative_to(ROOT))
        for name, path in public_functions.items()
        if references[name] == 0
    }
    assert unused == {}, f"Funções públicas sem uso ou teste: {unused}"


def test_ingestion_core_has_no_cloud_or_whatsapp_dependency() -> None:
    forbidden_roots = {"azure", "google", "twilio", "whatsapp"}
    violations: list[tuple[str, str]] = []

    for path in SOURCE.rglob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            imported: list[str] = []
            if isinstance(node, ast.Import):
                imported = [alias.name for alias in node.names]
            elif isinstance(node, ast.ImportFrom) and node.module:
                imported = [node.module]
            for module in imported:
                if module.split(".")[0].lower() in forbidden_roots:
                    violations.append((str(path.relative_to(ROOT)), module))

    assert violations == []
