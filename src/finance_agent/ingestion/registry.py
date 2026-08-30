"""Registro local de formatos aprovados, sem armazenar linhas financeiras."""

from __future__ import annotations

import json
import re
from pathlib import Path

from pydantic import ValidationError

from finance_agent.ingestion.models import (
    ColumnMapping,
    CsvSchemaProfile,
    FormatSpec,
    RegistryDocument,
    json_ready,
)
from finance_agent.ingestion.schema import normalize_column_name


class RegistryError(ValueError):
    pass


class MappingRegistry:
    def __init__(self, path: Path) -> None:
        self.path = path

    def load(self) -> RegistryDocument:
        if not self.path.exists():
            return RegistryDocument()
        try:
            payload = json.loads(self.path.read_text(encoding="utf-8"))
            return RegistryDocument.model_validate(payload)
        except (OSError, json.JSONDecodeError, ValidationError) as exc:
            raise RegistryError("O registro de formatos está inválido ou corrompido.") from exc

    def list_specs(self) -> tuple[FormatSpec, ...]:
        return tuple(self.load().formats)

    def learn(
        self,
        profile: CsvSchemaProfile,
        mapping: ColumnMapping,
        institution: str,
        currency: str,
        date_order: str | None = None,
    ) -> FormatSpec:
        if not mapping.is_complete:
            raise RegistryError("O mapeamento não contém os três campos mínimos.")
        clean_institution = institution.strip()
        if not clean_institution:
            raise RegistryError("Informe um nome para a instituição ou formato.")
        if len(clean_institution) > 80 or any(
            character in "\r\n\t" for character in clean_institution
        ):
            raise RegistryError("O nome do formato contém caracteres não permitidos.")
        clean_currency = currency.strip().upper()
        if len(clean_currency) != 3 or not clean_currency.isalpha():
            raise RegistryError("A moeda deve usar três letras no padrão ISO, como BRL ou USD.")
        if date_order not in {None, "ymd", "dmy", "mdy"}:
            raise RegistryError("A ordem da data deve ser ymd, dmy ou mdy.")

        slug = normalize_column_name(clean_institution)
        slug = re.sub(r"[^a-z0-9]+", "_", slug).strip("_") or "custom"
        amount_columns = frozenset(
            column
            for column in (mapping.amount, mapping.credit, mapping.debit)
            if column is not None
        )
        spec = FormatSpec(
            format_id=f"learned_csv_{slug}_{profile.signature[:8]}",
            institution=clean_institution,
            parser_id="generic_csv",
            currency=clean_currency,
            date_order=date_order,
            delimiter=profile.delimiter,
            expected_columns=profile.columns,
            required_columns=frozenset(
                {mapping.transaction_date, mapping.description} - {None}
            ),
            required_any_groups=(amount_columns,),
            mapping=mapping,
            learned=True,
        )

        document = self.load()
        retained = [item for item in document.formats if item.format_id != spec.format_id]
        retained.append(spec)
        updated = RegistryDocument(version=document.version, formats=retained)
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            temporary = self.path.with_suffix(f"{self.path.suffix}.tmp")
            temporary.write_text(
                json.dumps(json_ready(updated), ensure_ascii=False, indent=2) + "\n",
                encoding="utf-8",
            )
            temporary.replace(self.path)
        except OSError as exc:
            raise RegistryError("O registro de formatos não pôde ser salvo.") from exc
        return spec
