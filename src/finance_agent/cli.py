"""Interface local segura para analisar e persistir extratos."""

from __future__ import annotations

import argparse
import json
from collections.abc import Sequence
from pathlib import Path

from finance_agent.application.ingest_file import ingest_file, safe_summary_lines
from finance_agent.application.persist_ingestion import (
    ingest_and_persist,
    safe_persistence_lines,
)
from finance_agent.ingestion.models import IngestionStatus, json_ready
from finance_agent.persistence.models import PersistenceStatus
from finance_agent.persistence.repository import (
    DEFAULT_DATABASE_PATH,
    PersistenceError,
    SQLiteFinanceRepository,
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="finance-agent")
    commands = parser.add_subparsers(dest="command", required=True)
    ingest = commands.add_parser("ingest", help="analisa um CSV e opcionalmente persiste")
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
    ingest.add_argument(
        "--persist",
        action="store_true",
        help="grava o resultado concluído no SQLite",
    )
    ingest.add_argument(
        "--database",
        type=Path,
        default=DEFAULT_DATABASE_PATH,
        help="arquivo SQLite privado",
    )

    database = commands.add_parser("db", help="administra o banco SQLite local")
    database_commands = database.add_subparsers(dest="database_command", required=True)
    for name, help_text in (
        ("init", "cria ou atualiza o schema"),
        ("summary", "exibe apenas contagens seguras"),
    ):
        database_command = database_commands.add_parser(name, help=help_text)
        database_command.add_argument(
            "--database",
            type=Path,
            default=DEFAULT_DATABASE_PATH,
            help="arquivo SQLite privado",
        )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)

    if args.command == "db":
        repository = SQLiteFinanceRepository(args.database)
        try:
            if args.database_command == "init":
                migration = repository.initialize()
                print("Banco SQLite pronto.")
                print(f"Versão do banco: {migration.schema_version}")
                print(f"Migrações aplicadas agora: {migration.migrations_applied}")
                return 0
            summary = repository.summary()
        except PersistenceError as exc:
            print("Banco SQLite indisponível.")
            print(f"Erro seguro: {exc}")
            return 1
        print(f"Versão do banco: {summary.schema_version}")
        print(f"Tentativas de importação: {summary.import_attempts}")
        print(f"Importações concluídas: {summary.completed_imports}")
        print(f"Transações: {summary.transactions}")
        print(f"Pendências abertas: {summary.open_pending}")
        print(f"Candidatas a duplicidade: {summary.duplicate_candidates}")
        return 0

    if args.persist:
        try:
            result = ingest_and_persist(
                args.file,
                database_path=args.database,
                registry_path=args.registry,
                approve_generic_as=args.approve_format,
                generic_currency=args.currency,
                generic_date_order=args.date_order,
            )
        except PersistenceError as exc:
            print("Persistência: failed")
            print(f"Erro seguro: {exc}")
            return 1
        if args.json:
            payload = {
                "ingestion": (
                    json_ready(result.ingestion.summary) if result.ingestion is not None else None
                ),
                "persistence": json_ready(result.persistence),
            }
            print(json.dumps(payload, ensure_ascii=False, indent=2))
        else:
            if result.ingestion is not None:
                print("\n".join(safe_summary_lines(result.ingestion)))
                print("---")
            else:
                print("Análise: dispensada; o arquivo já havia sido importado.")
            print("\n".join(safe_persistence_lines(result)))
        if result.persistence.status == PersistenceStatus.FAILED:
            return 1
        if result.persistence.status == PersistenceStatus.NOT_STORED:
            if result.ingestion is not None:
                if result.ingestion.summary.status == IngestionStatus.FAILED:
                    return 1
                if result.ingestion.summary.status == IngestionStatus.BLOCKED:
                    return 2
            return 1
        return 0

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
