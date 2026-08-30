"""Interface local segura para inspecionar extratos sem persistência."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Sequence

from finance_agent.application.ingest_file import ingest_file, safe_summary_lines
from finance_agent.ingestion.models import IngestionStatus, json_ready


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="finance-agent")
    commands = parser.add_subparsers(dest="command", required=True)
    ingest = commands.add_parser("ingest", help="analisa um CSV sem gravar no banco")
    ingest.add_argument("file", type=Path)
    ingest.add_argument(
        "--registry",
        type=Path,
        default=Path("private_data/config/bank_mappings.json"),
        help="registro privado de formatos aprovados",
    )
    ingest.add_argument(
        "--approve-format",
        dest="approve_format",
        help="aprova o mapeamento sugerido com o nome informado",
    )
    ingest.add_argument(
        "--currency",
        help="moeda ISO obrigatória ao aprovar um formato, por exemplo BRL ou USD",
    )
    ingest.add_argument(
        "--date-order",
        choices=("ymd", "dmy", "mdy"),
        help="ordem de data do formato aprovado; omitir mantém datas ambíguas pendentes",
    )
    ingest.add_argument("--json", action="store_true", help="exibe somente o resumo em JSON")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    outcome = ingest_file(
        args.file,
        registry_path=args.registry,
        approve_generic_as=args.approve_format,
        generic_currency=args.currency,
        generic_date_order=args.date_order,
    )
    if args.json:
        print(json.dumps(json_ready(outcome.summary), ensure_ascii=False, indent=2))
    else:
        print("\n".join(safe_summary_lines(outcome)))
    if outcome.summary.status == IngestionStatus.FAILED:
        return 1
    if outcome.summary.status == IngestionStatus.BLOCKED:
        return 2
    return 0
