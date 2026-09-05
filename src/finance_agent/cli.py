"""Interface local segura para analisar e persistir extratos."""

from __future__ import annotations

import argparse
import json
from collections.abc import Sequence
from pathlib import Path
from uuid import UUID

from finance_agent.application.ingest_file import ingest_file, safe_summary_lines
from finance_agent.application.persist_ingestion import (
    ingest_and_persist,
    safe_persistence_lines,
)
from finance_agent.classification.engine import classify_pending_transactions
from finance_agent.classification.models import TransactionNature
from finance_agent.ingestion.models import IngestionStatus, json_ready
from finance_agent.persistence.classification_repository import (
    ClassificationPersistenceError,
    SQLiteClassificationRepository,
)
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

    categories = commands.add_parser("categories", help="administra categorias pessoais")
    category_commands = categories.add_subparsers(dest="category_command", required=True)
    category_add = category_commands.add_parser("add", help="adiciona uma categoria")
    category_add.add_argument("name", help="nome não sensível da categoria")
    category_commands.add_parser("list", help="lista categorias")
    for action in ("enable", "disable"):
        command = category_commands.add_parser(action, help=f"{action} uma categoria")
        command.add_argument("category_id", type=UUID)
    for command in category_commands.choices.values():
        command.add_argument(
            "--database",
            type=Path,
            default=DEFAULT_DATABASE_PATH,
            help="arquivo SQLite privado",
        )

    rules = commands.add_parser("rules", help="consulta e ativa/desativa regras")
    rule_commands = rules.add_subparsers(dest="rule_command", required=True)
    rule_commands.add_parser("list", help="lista regras sem revelar seus critérios")
    for action in ("enable", "disable"):
        command = rule_commands.add_parser(action, help=f"{action} uma regra")
        command.add_argument("rule_id", type=UUID)
    for command in rule_commands.choices.values():
        command.add_argument(
            "--database",
            type=Path,
            default=DEFAULT_DATABASE_PATH,
            help="arquivo SQLite privado",
        )

    classify = commands.add_parser("classify", help="classifica e revisa transações")
    classify_commands = classify.add_subparsers(dest="classify_command", required=True)
    classify_run = classify_commands.add_parser("run", help="executa as regras por prioridade")
    classify_run.add_argument("--limit", type=int, default=500)
    classify_commands.add_parser("summary", help="exibe somente contagens seguras")
    classify_pending = classify_commands.add_parser(
        "pending", help="lista IDs e motivos de revisão"
    )
    classify_pending.add_argument("--limit", type=int, default=100)
    classify_correct = classify_commands.add_parser(
        "correct", help="confirma uma classificação manual"
    )
    classify_correct.add_argument("transaction_id", type=UUID)
    classify_correct.add_argument(
        "--nature",
        required=True,
        choices=tuple(item.value for item in TransactionNature),
    )
    classify_correct.add_argument("--category")
    classify_correct.add_argument(
        "--remember",
        action="store_true",
        help="cria regra exata para descrição e instituição desta transação",
    )
    classify_correct.add_argument("--priority", type=int, default=800)
    classify_review = classify_commands.add_parser(
        "review", help="marca uma transação para revisão humana"
    )
    classify_review.add_argument("transaction_id", type=UUID)
    for command in classify_commands.choices.values():
        command.add_argument(
            "--database",
            type=Path,
            default=DEFAULT_DATABASE_PATH,
            help="arquivo SQLite privado",
        )
    return parser


def _run_category_command(args: argparse.Namespace) -> int:
    repository = SQLiteClassificationRepository(args.database)
    if args.category_command == "add":
        category = repository.create_category(args.name)
        print("Categoria pronta.")
        print(f"ID: {category.id}")
        print(f"Nome: {category.name}")
        print(f"Ativa: {'sim' if category.is_active else 'não'}")
        return 0
    if args.category_command == "list":
        categories = repository.list_categories()
        print(f"Categorias: {len(categories)}")
        for category in categories:
            state = "ativa" if category.is_active else "inativa"
            print(f"{category.id} | {category.name} | {state}")
        return 0
    active = args.category_command == "enable"
    changed = repository.set_category_active(args.category_id, active=active)
    print("Categoria atualizada." if changed else "Categoria não encontrada.")
    return 0 if changed else 1


def _run_rule_command(args: argparse.Namespace) -> int:
    repository = SQLiteClassificationRepository(args.database)
    if args.rule_command == "list":
        categories = {category.id: category.name for category in repository.list_categories()}
        rules = repository.list_rules()
        print(f"Regras: {len(rules)}")
        for rule in rules:
            state = "ativa" if rule.is_enabled else "inativa"
            category = categories.get(rule.category_id, "-")
            print(
                f"{rule.id} | prioridade={rule.priority} | natureza={rule.nature.value} | "
                f"categoria={category} | critérios={rule.criteria_count} | {state}"
            )
        return 0
    enabled = args.rule_command == "enable"
    changed = repository.set_rule_enabled(args.rule_id, enabled=enabled)
    print("Regra atualizada." if changed else "Regra não encontrada.")
    return 0 if changed else 1


def _run_classification_command(args: argparse.Namespace) -> int:
    repository = SQLiteClassificationRepository(args.database)
    if args.classify_command == "run":
        result = classify_pending_transactions(repository, limit=args.limit)
        print("Classificação concluída.")
        print(f"Transações examinadas: {result.examined}")
        print(f"Classificadas automaticamente: {result.classified}")
        print(f"Marcadas para revisão: {result.pending_review}")
        print(f"Já classificadas e preservadas: {result.skipped_with_decision}")
        return 0
    if args.classify_command == "summary":
        summary = repository.classification_summary()
        print(f"Categorias ativas: {summary.active_categories}")
        print(f"Regras ativas: {summary.enabled_rules}")
        print(f"Transações classificadas: {summary.classified_transactions}")
        print(f"Revisões abertas: {summary.open_reviews}")
        print(f"Correções registradas: {summary.corrections}")
        return 0
    if args.classify_command == "pending":
        reviews = repository.list_open_reviews(limit=args.limit)
        print(f"Revisões abertas: {len(reviews)}")
        for review in reviews:
            print(
                f"{review.transaction_id} | motivo={review.reason.value} | "
                f"regras_candidatas={len(review.candidate_rule_ids)}"
            )
        return 0
    if args.classify_command == "review":
        review = repository.mark_for_review(args.transaction_id)
        print("Transação marcada para revisão.")
        print(f"ID da revisão: {review.id}")
        return 0

    correction = repository.correct_classification(
        args.transaction_id,
        nature=TransactionNature(args.nature),
        category_name=args.category,
        remember=args.remember,
        rule_priority=args.priority,
    )
    print("Classificação confirmada pela usuária.")
    print(f"Transação: {correction.decision.transaction_id}")
    print(f"Natureza: {correction.decision.nature.value}")
    print(f"Categoria: {correction.decision.category_name or '-'}")
    print(f"Regra lembrada: {'sim' if correction.remembered_rule_id else 'não'}")
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)

    if args.command in {"categories", "rules", "classify"}:
        try:
            if args.command == "categories":
                return _run_category_command(args)
            if args.command == "rules":
                return _run_rule_command(args)
            return _run_classification_command(args)
        except (ClassificationPersistenceError, PersistenceError, ValueError) as exc:
            print("Classificação indisponível.")
            print(f"Erro seguro: {exc}")
            return 1

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
