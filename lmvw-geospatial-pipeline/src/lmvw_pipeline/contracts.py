"""Single source of truth for CSV exports, validation and SQL Server DDL."""
from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from typing import Any


@dataclass(frozen=True)
class Column:
    name: str
    kind: str = "text"
    nullable: bool = True
    length: int | None = None

    @property
    def sql_type(self) -> str:
        if self.kind == "text":
            return f"NVARCHAR({self.length or 'MAX'}) COLLATE Latin1_General_100_BIN2"
        return {"json": "NVARCHAR(MAX)", "int": "BIGINT", "bool": "BIT", "decimal": "DECIMAL(38,12)",
                "date": "DATE", "datetime": "DATETIMEOFFSET(7)"}[self.kind]


@dataclass(frozen=True)
class ForeignKey:
    columns: tuple[str, ...]
    parent: str
    parent_columns: tuple[str, ...]


@dataclass(frozen=True)
class Table:
    name: str
    columns: tuple[Column, ...]
    primary_key: tuple[str, ...]
    foreign_keys: tuple[ForeignKey, ...] = ()


def t(name: str, length: int | None = None, nullable: bool = True) -> Column:
    return Column(name, "text", nullable, length)


def c(name: str, kind: str = "int", nullable: bool = True) -> Column:
    return Column(name, kind, nullable)


RUN = t("run_id", 36, False)
RECORD = t("record_id", 64, False)
RUN_FK = ForeignKey(("run_id",), "pipeline_run", ("run_id",))
PLAN_FK = ForeignKey(("run_id", "record_id"), "plans", ("run_id", "record_id"))
DOC_FK = ForeignKey(("run_id", "document_id"), "dso_documents", ("run_id", "document_id"))
GEOMETRY = (t("geometry_wkt"), c("geometry_geojson_wgs84", "json"), t("crs", 32))
SOURCE_COMMON = (t("source_feature_id", 100, False), c("retrieved_at", "datetime", False))


def table(name: str, columns: tuple[Column, ...], key: tuple[str, ...], *fks: ForeignKey) -> Table:
    return Table(name, (RUN, *columns), ("run_id", *key), (RUN_FK, *fks))


TABLES = (
    Table("pipeline_run", (RUN, t("delivery_id", 64, False), t("mode", 20, False), t("status", 40, False),
                          c("snapshot_utc", "datetime", False), c("started_at", "datetime", False),
                          c("completed_at", "datetime", False), t("rule_version", 32, False),
                          t("config_sha256", 64, False), c("source_metadata_json", "json", False)), ("run_id",)),
    table("source_status", (t("source_name", 20, False), t("status", 32, False), t("environment", 32, False),
                            c("record_count", nullable=False), t("message")), ("source_name",)),
    table("plans", (RECORD, t("delivery_id", 64, False), c("source_row_number", nullable=False),
                    t("source_record_hash", 64, False), t("municipality", 300), t("plan_name", 1000), t("koppelcode", 100),
                    c("confidential", "bool"), c("gross_capacity"), c("demolition"), c("net_capacity_reported"),
                    c("net_capacity_calculated"), c("temporary_homes"), t("plan_type", 300), t("plan_status", 300),
                    t("status_code", 8), t("hard_soft", 16, False), *GEOMETRY,
                    t("processing_status", 16, False), c("error_count", nullable=False),
                    c("warning_count", nullable=False), c("raw_payload_json", "json", False)), ("record_id",)),
    table("plan_phasing", (RECORD, c("period_start", nullable=False), c("period_end", nullable=False),
                           t("period_label", 80, False), c("sort_order", nullable=False), c("planned_homes")),
          ("record_id", "period_start", "period_end"), PLAN_FK),
    table("plan_breakdown", (RECORD, t("category_group", 40, False), t("category_code", 80, False),
                             t("source_field", 300, False), c("homes")), ("record_id", "category_group", "category_code"), PLAN_FK),
    table("quarantine", (RECORD, c("source_row_number", nullable=False), c("error_count", nullable=False),
                         c("raw_payload_json", "json", False)), ("record_id",), PLAN_FK),
    table("dq_issues", (t("issue_id", 64, False), t("record_id", 64), t("source_name", 40, False),
                        t("source_object_id", 2000), c("source_row_number"), t("rule_id", 80, False),
                        t("category", 40, False), t("severity", 16, False), t("field_name", 300, False),
                        t("source_value"), t("message", None, False)), ("issue_id",), PLAN_FK),
    table("bag_panden", (t("bag_pand_id", 16, False), *SOURCE_COMMON, t("status", 300), c("bouwjaar"),
                          c("aantal_verblijfsobjecten"), t("gebruiksdoel", 1000), c("documentdatum", "date"),
                          t("documentnummer", 1000), *GEOMETRY), ("bag_pand_id",)),
    table("bag_verblijfsobjecten", (t("bag_verblijfsobject_id", 16, False), *SOURCE_COMMON,
                                    t("status", 300), t("gebruiksdoel", 1000), c("oppervlakte_m2"),
                                    t("postcode", 16), t("openbare_ruimte_naam", 1000), c("huisnummer"),
                                    t("huisletter", 50), t("huisnummertoevoeging", 100), c("documentdatum", "date"),
                                    t("documentnummer", 1000), *GEOMETRY), ("bag_verblijfsobject_id",)),
    table("bag_vbo_pand", (t("bag_verblijfsobject_id", 16, False), t("bag_pand_id", 16, False),
                           t("relation_basis", 80, False), c("retrieved_at", "datetime", False)),
          ("bag_verblijfsobject_id", "bag_pand_id"),
          ForeignKey(("run_id", "bag_verblijfsobject_id"), "bag_verblijfsobjecten", ("run_id", "bag_verblijfsobject_id")),
          ForeignKey(("run_id", "bag_pand_id"), "bag_panden", ("run_id", "bag_pand_id"))),
    table("brk_percelen", (t("brk_namespace", 100, False), t("brk_local_id", 100, False), *SOURCE_COMMON,
                           t("kadastrale_gemeente_code", 100), t("kadastrale_gemeente_naam", 300), t("sectie", 50),
                           c("perceelnummer"), c("kadastrale_grootte_m2", "decimal"), t("grootte_status", 300),
                           t("historie_status", 300), *GEOMETRY), ("brk_namespace", "brk_local_id")),
    table("dso_documents", (t("document_id", 64, False), t("source_type", 64, False), t("environment", 32, False),
                            t("native_id", 2000, False), t("document_type", 500), t("title", 4000), c("document_date", "date"),
                            t("authority_name", 1000), t("authority_code", 100), t("plan_status", 300), t("rule_status", 300),
                            t("dossier_status", 300), t("dossier_id", 1000), t("reference_number", 1000), t("publication_id", 1000),
                            c("geometry_ids_json", "json", False), *GEOMETRY, t("geometry_status", 32, False),
                            t("text_status", 32, False), t("source_url", 4000), c("retrieved_at", "datetime", False)), ("document_id",)),
    table("dso_document_text", (t("document_id", 64, False), t("publication_text", None, False),
                                t("text_sha256", 64, False), c("character_count", nullable=False),
                                c("retrieved_at", "datetime", False)), ("document_id",), DOC_FK),
    table("plan_bag_vbo", (RECORD, t("bag_verblijfsobject_id", 16, False), t("match_method", 100, False),
                           t("spatial_relation", 100, False)), ("record_id", "bag_verblijfsobject_id"), PLAN_FK,
          ForeignKey(("run_id", "bag_verblijfsobject_id"), "bag_verblijfsobjecten", ("run_id", "bag_verblijfsobject_id"))),
    table("plan_bag_pand", (RECORD, t("bag_pand_id", 16, False), t("match_method", 100, False),
                            t("spatial_relation", 100, False), c("overlap_area_m2", "decimal"), c("via_vbo_count", nullable=False)),
          ("record_id", "bag_pand_id"), PLAN_FK,
          ForeignKey(("run_id", "bag_pand_id"), "bag_panden", ("run_id", "bag_pand_id"))),
    table("plan_brk_perceel", (RECORD, t("brk_namespace", 100, False), t("brk_local_id", 100, False),
                               t("match_method", 100, False), c("intersection_area_m2", "decimal", False),
                               c("overlap_pct_plan", "decimal", False), c("overlap_pct_perceel", "decimal", False)),
          ("record_id", "brk_namespace", "brk_local_id"), PLAN_FK,
          ForeignKey(("run_id", "brk_namespace", "brk_local_id"), "brk_percelen", ("run_id", "brk_namespace", "brk_local_id"))),
    table("plan_dso", (RECORD, t("document_id", 64, False), t("search_geometry_hash", 64, False),
                       t("relation_basis", 100, False), t("relation_status", 100, False),
                       c("spatial_verified", "bool", False), c("substantively_confirmed", "bool", False),
                       c("overlap_area_m2", "decimal"), c("retrieved_at", "datetime", False)),
          ("record_id", "document_id"), PLAN_FK, DOC_FK),
)
BY_NAME = {spec.name: spec for spec in TABLES}


def schema_document() -> dict[str, Any]:
    return json.loads(json.dumps({"version": "1.0.0", "dialect": "SQL Server", "encoding": "utf-8", "delimiter": ",",
            "newline": "LF", "null_token": "\\N", "load_order": [t.name for t in TABLES],
            "tables": [asdict(spec) for spec in TABLES]}))


def sql_ddl() -> str:
    lines = ["-- Generated from lmvw_pipeline.contracts. No source data or credentials.",
             "-- First installation into an empty lmvw schema; do not disable constraints.",
             "IF SCHEMA_ID(N'lmvw') IS NULL EXEC(N'CREATE SCHEMA [lmvw]');", "GO", ""]
    for spec in TABLES:
        definitions = [f"    [{col.name}] {col.sql_type} {'NULL' if col.nullable else 'NOT NULL'}" for col in spec.columns]
        keys = ", ".join(f"[{k}]" for k in spec.primary_key)
        definitions.append(f"    CONSTRAINT [PK_{spec.name}] PRIMARY KEY ({keys})")
        for i, fk in enumerate(spec.foreign_keys):
            child = ", ".join(f"[{k}]" for k in fk.columns)
            parent = ", ".join(f"[{k}]" for k in fk.parent_columns)
            definitions.append(f"    CONSTRAINT [FK_{spec.name}_{i}] FOREIGN KEY ({child}) REFERENCES [lmvw].[{fk.parent}] ({parent})")
        lines += [f"CREATE TABLE [lmvw].[{spec.name}] (", ",\n".join(definitions), ");", "GO", ""]
    return "\n".join(lines)
