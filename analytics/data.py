"""Load one export run and calculate metrics at the correct grain.

No pipeline imports, API requests, database connection or automatic source edits.
A plan's key is (run_id, record_id), never its potentially shared Koppelcode.
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parent
DEMO = ROOT / "demo" / "database_ready"
KEY = ["run_id", "record_id"]
VALID = {"READY", "WARNING"}
RELATIONS = {
    "BAG panden": ("plan_bag_pand", "bag_panden", ["bag_pand_id"], "BAG"),
    "BAG verblijfsobjecten": ("plan_bag_vbo", "bag_verblijfsobjecten", ["bag_verblijfsobject_id"], "BAG"),
    "BRK percelen": ("plan_brk_perceel", "brk_percelen", ["brk_namespace", "brk_local_id"], "BRK"),
    "DSO documenten": ("plan_dso", "dso_documents", ["document_id"], "DSO"),
}
# Only presentation fields are read. Raw/quarantine payloads and publication texts
# deliberately stay outside this application and its downloaded reports.
COLUMNS = {
    "pipeline_run": ["run_id", "mode", "status", "snapshot_utc", "completed_at"],
    "source_status": ["run_id", "source_name", "status", "environment", "record_count"],
    "plans": KEY + ["source_row_number", "municipality", "plan_name", "koppelcode", "confidential",
                    "gross_capacity", "demolition", "net_capacity_calculated", "temporary_homes",
                    "plan_type", "plan_status", "hard_soft", "geometry_wkt", "crs",
                    "processing_status", "error_count", "warning_count"],
    "plan_phasing": KEY + ["period_start", "period_end", "period_label", "sort_order", "planned_homes"],
    "plan_breakdown": KEY + ["category_group", "category_code", "source_field", "homes"],
    "dq_issues": ["run_id", "issue_id", "record_id", "source_name", "rule_id", "category", "severity",
                  "field_name", "message"],
    "bag_panden": ["run_id", "bag_pand_id", "status", "bouwjaar", "geometry_wkt", "crs"],
    "bag_verblijfsobjecten": ["run_id", "bag_verblijfsobject_id", "status", "gebruiksdoel", "oppervlakte_m2",
                            "geometry_wkt", "crs"],
    "brk_percelen": ["run_id", "brk_namespace", "brk_local_id", "sectie", "perceelnummer", "geometry_wkt", "crs"],
    "dso_documents": ["run_id", "document_id", "title", "document_type", "document_date", "environment",
                      "geometry_wkt", "crs"],
    "plan_bag_pand": KEY + ["bag_pand_id", "match_method", "spatial_relation", "overlap_area_m2", "via_vbo_count"],
    "plan_bag_vbo": KEY + ["bag_verblijfsobject_id", "match_method", "spatial_relation"],
    "plan_brk_perceel": KEY + ["brk_namespace", "brk_local_id", "match_method", "intersection_area_m2",
                               "overlap_pct_plan", "overlap_pct_perceel"],
    "plan_dso": KEY + ["document_id", "relation_basis", "relation_status", "spatial_verified",
                       "substantively_confirmed", "overlap_area_m2"],
}
NUMERIC = {"source_row_number", "gross_capacity", "demolition", "net_capacity_calculated", "temporary_homes",
           "error_count", "warning_count", "period_start", "period_end", "sort_order", "planned_homes", "homes",
           "record_count", "bouwjaar", "oppervlakte_m2", "overlap_area_m2", "via_vbo_count", "intersection_area_m2",
           "overlap_pct_plan", "overlap_pct_perceel"}
BOOL = {"confidential", "spatial_verified", "substantively_confirmed"}


class DataError(ValueError):
    """An input problem suitable for displaying without raw data or secrets."""


@dataclass
class Bundle:
    path: Path
    tables: dict[str, pd.DataFrame]
    manifest: dict

    def __getitem__(self, name: str) -> pd.DataFrame:
        return self.tables[name]

    @property
    def run_id(self) -> str:
        return str(self["pipeline_run"].iloc[0]["run_id"])

    @property
    def mode(self) -> str:
        return str(self["pipeline_run"].iloc[0]["mode"])

    @property
    def classification(self) -> str:
        # Fixture mode only describes the external sources. In older pipelines it
        # incorrectly implies synthetic plans too. NEVER use it as publication approval.
        if self.path.resolve() == DEMO.resolve():
            return "MEEGELEVERDE SYNTHETISCHE DEMO - GEEN ECHTE WONINGBOUWCIJFERS"
        return "LOKALE INTERNE ANALYSE - PUBLICATIE NIET GOEDGEKEURD"


def load_bundle(folder: str | Path) -> Bundle:
    path = Path(folder).expanduser().resolve()
    if not (path / "manifest.json").is_file():
        raise DataError("Selecteer de volledige database_ready-map, niet het ruwe plans.csv-bestand.")
    try:
        manifest = json.loads((path / "manifest.json").read_text(encoding="utf-8"))
    except (ValueError, OSError) as exc:
        raise DataError("Het exportmanifest is niet leesbaar.") from exc
    tables = {}
    for name, columns in COLUMNS.items():
        file = path / f"{name}.csv"
        if not file.is_file():
            raise DataError(f"Exporttabel ontbreekt: {file.name}")
        spec = manifest.get("files", {}).get(file.name)
        if not isinstance(spec, dict) or not spec.get("sha256"):
            raise DataError(f"Checksum ontbreekt voor {file.name}; maak de export opnieuw met deel 1.")
        # Hash only fixed, known filenames, not arbitrary paths from a manifest.
        sha = hashlib.sha256()
        with file.open("rb") as stream:
            for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                sha.update(chunk)
        if sha.hexdigest() != spec["sha256"]:
            raise DataError(f"{file.name} is gewijzigd na export; pas gegenereerde tabellen niet handmatig aan.")
        try:
            frame = pd.read_csv(file, sep=",", encoding="utf-8-sig", dtype="string", keep_default_na=False,
                                na_values=[r"\N"], usecols=columns)
            frame = frame[columns]
            if len(frame) != spec["rows"]:
                raise DataError(f"Onjuist rijaantal in {file.name}.")
            for col in set(frame) & NUMERIC:
                frame[col] = pd.to_numeric(frame[col], errors="raise").astype("Float64")
            for col in set(frame) & BOOL:
                values = frame[col].dropna()
                if not values.isin(["0", "1", "true", "false", "True", "False"]).all():
                    raise DataError(f"Ongeldige boolean in {file.name}: {col}")
                frame[col] = frame[col].map({"0": False, "1": True, "true": True, "false": False,
                                             "True": True, "False": False}).astype("boolean")
        except (ValueError, KeyError, pd.errors.ParserError) as exc:
            raise DataError(f"Onverwacht schema of datatype in {file.name}.") from exc
        tables[name] = frame
    run = tables["pipeline_run"]
    if len(run) != 1 or run["run_id"].isna().any():
        raise DataError("Selecteer precies een export-run; runs mogen niet worden samengevoegd.")
    run_id = run.iloc[0]["run_id"]
    for name, frame in tables.items():
        if frame["run_id"].isna().any() or not frame["run_id"].eq(run_id).all():
            raise DataError(f"Run-identifiers komen niet overeen in {name}.")
    plans = tables["plans"]
    if plans["record_id"].isna().any() or plans.duplicated(KEY).any():
        raise DataError("Planrecord-identifiers ontbreken of zijn dubbel; geen automatische deduplicatie.")
    if not plans["processing_status"].isin(VALID | {"REJECTED"}).all():
        raise DataError("Onbekende verwerkingsstatus in plans.csv.")
    for name in ("plan_phasing", "plan_breakdown", *[x[0] for x in RELATIONS.values()]):
        frame = tables[name]
        if frame["record_id"].isna().any() or not frame["record_id"].isin(plans["record_id"]).all():
            raise DataError(f"Verwijzing naar een ontbrekend plan in {name}.")
    unique = {"plan_phasing": KEY + ["period_start", "period_end"],
              "plan_breakdown": KEY + ["category_group", "category_code"],
              "dq_issues": ["run_id", "issue_id"], "source_status": ["run_id", "source_name"]}
    for rel, source, ids, _ in RELATIONS.values():
        unique[rel], unique[source] = KEY + ids, ["run_id"] + ids
        linked = tables[rel].merge(tables[source][["run_id"] + ids], on=["run_id"] + ids,
                                   how="left", indicator=True, validate="many_to_one")
        if linked["_merge"].eq("left_only").any():
            raise DataError(f"Ontbrekend bronobject in {rel}.")
    for name, pk in unique.items():
        if tables[name].duplicated(pk).any():
            raise DataError(f"Dubbele sleutel in {name}; tellingen zouden onjuist worden.")
    return Bundle(path, tables, manifest)


def filter_plans(bundle: Bundle, municipalities: list[str] | None = None,
                 hardness: list[str] | None = None) -> pd.DataFrame:
    plans = bundle["plans"]
    if municipalities is not None:
        plans = plans[plans["municipality"].fillna("(ontbreekt)").isin(municipalities)]
    if hardness is not None:
        plans = plans[plans["hard_soft"].isin(hardness)]
    return plans.copy()


def eligible(plans: pd.DataFrame) -> pd.DataFrame:
    return plans[plans["processing_status"].isin(VALID)].copy()


def selected_rows(frame: pd.DataFrame, plans: pd.DataFrame) -> pd.DataFrame:
    return frame.merge(plans[KEY], on=KEY, how="inner", validate="many_to_one")


def total(series: pd.Series) -> float | None:
    """Unknown or an empty population is NOT a measured zero."""
    value = series.sum(min_count=1)
    return None if pd.isna(value) else float(value)


def kpis(plans: pd.DataFrame) -> dict:
    accepted = eligible(plans)
    return {"input": len(plans), "accepted": len(accepted), "rejected": len(plans) - len(accepted),
            "gross": total(accepted["gross_capacity"]), "demolition": total(accepted["demolition"]),
            "net": total(accepted["net_capacity_calculated"]),
            "acceptance_rate": len(accepted) / len(plans) if len(plans) else None}


def capacity_by(plans: pd.DataFrame, group: str) -> pd.DataFrame:
    data = eligible(plans)
    return data.groupby(group, dropna=False, as_index=False).agg(
        gross=("gross_capacity", lambda s: s.sum(min_count=1)),
        net=("net_capacity_calculated", lambda s: s.sum(min_count=1)), plans=("record_id", "size"))


def phasing(bundle: Bundle, plans: pd.DataFrame) -> pd.DataFrame:
    rows = selected_rows(bundle["plan_phasing"], eligible(plans))
    return rows.groupby(["period_start", "period_end", "period_label"], as_index=False).agg(
        homes=("planned_homes", lambda s: s.sum(min_count=1)), missing=("planned_homes", lambda s: s.isna().sum())
    ).sort_values(["period_start", "period_end"])


def breakdown(bundle: Bundle, plans: pd.DataFrame, group: str) -> pd.DataFrame:
    rows = selected_rows(bundle["plan_breakdown"], eligible(plans))
    rows = rows[rows["category_group"].eq(group)]
    return rows.groupby(["category_code", "source_field"], as_index=False).agg(
        homes=("homes", lambda s: s.sum(min_count=1)), missing=("homes", lambda s: s.isna().sum()))


def scoped_issues(bundle: Bundle, plans: pd.DataFrame) -> pd.DataFrame:
    rows = selected_rows(bundle["dq_issues"], plans)
    names = plans[KEY + ["municipality", "plan_name", "source_row_number"]]
    return rows.merge(names, on=KEY, how="left", validate="many_to_one")


def issue_rules(bundle: Bundle, plans: pd.DataFrame) -> pd.DataFrame:
    issues = scoped_issues(bundle, plans)
    return issues.groupby(["rule_id", "severity"], as_index=False).agg(
        findings=("issue_id", "size"), records=("record_id", "nunique")
    ).sort_values("findings", ascending=False)


def source_metrics(bundle: Bundle, plans: pd.DataFrame) -> pd.DataFrame:
    accepted = eligible(plans)
    statuses = bundle["source_status"].set_index("source_name")["status"].to_dict()
    rows = []
    for label, (rel, _, ids, source) in RELATIONS.items():
        links = selected_rows(bundle[rel], accepted)
        state = statuses.get(source, "UNKNOWN")
        queried = state not in {"NOT_QUERIED", "DISABLED", "UNKNOWN"}
        count = len(links[KEY].drop_duplicates())
        rows.append({"source": label, "status": state, "objects": len(links[ids].drop_duplicates()) if queried else None,
                     "relations": len(links) if queried else None, "linked_plans": count if queried else None,
                     "eligible_plans": len(accepted),
                     "coverage_pct": 100 * count / len(accepted) if queried and len(accepted) else None})
    return pd.DataFrame(rows)


def source_objects(bundle: Bundle, plans: pd.DataFrame, label: str) -> pd.DataFrame:
    rel, source, ids, _ = RELATIONS[label]
    links = selected_rows(bundle[rel], plans)
    return links.merge(bundle[source], on=["run_id"] + ids, how="left", validate="many_to_one")


def dso_evidence(bundle: Bundle, plans: pd.DataFrame) -> pd.DataFrame:
    rows = selected_rows(bundle["plan_dso"], eligible(plans))
    return rows.groupby("relation_status", as_index=False).agg(
        relations=("document_id", "size"), documents=("document_id", "nunique"))


def number(value: float | int | None) -> str:
    return "n.v.t." if value is None or pd.isna(value) else f"{value:,.0f}".replace(",", ".")


def findings(bundle: Bundle, plans: pd.DataFrame) -> list[str]:
    """Descriptive observations, not claims about actual delivery or causality."""
    metrics = kpis(plans)
    notes = [f"Van {metrics['input']} aangeleverde planrecords in deze selectie zijn er "
             f"{metrics['accepted']} toegelaten en {metrics['rejected']} afgekeurd. "
             "Afgekeurde records tellen niet mee in de capaciteitsgrafieken."]
    if metrics["accepted"]:
        notes.append(f"De toegelaten records bevatten {number(metrics['gross'])} bruto geplande woningen en "
                     f"{number(metrics['net'])} netto toevoegingen (bruto minus sloop/onttrekkingen). "
                     "Dit is plancapaciteit, geen gemeten bouwrealisatie.")
        hard = eligible(plans)
        hard_capacity = total(hard.loc[hard["hard_soft"].eq("HARD"), "gross_capacity"])
        if hard_capacity is not None and metrics["gross"] and metrics["gross"] > 0:
            notes.append(f"{100 * hard_capacity / metrics['gross']:.1f}% van de toegelaten bruto capaciteit "
                         "valt onder een harde planstatus. Dit is een classificatie, geen realisatiekans.")
    else:
        notes.append("Geen records toegelaten: er is geen bruikbare capaciteitspopulatie. "
                     "Lege kaarten en bronrelaties mogen niet als nul woningen of nul bronobjecten worden gelezen.")
    rules = issue_rules(bundle, plans)
    if not rules.empty:
        grouped = rules.groupby("rule_id")["findings"].sum().sort_values(ascending=False)
        notes.append(f"De meest voorkomende regel is {grouped.index[0]} met {int(grouped.iloc[0])} bevindingen. "
                     "Een planrecord kan meerdere bevindingen hebben.")
    phases = phasing(bundle, plans)
    if not phases.empty and phases["missing"].sum():
        notes.append(f"Aantal ontbrekende faseringswaarden: {int(phases['missing'].sum())}. "
                     "Grafieken tonen alleen bekende aantallen; ontbrekend is niet als nul ingevuld.")
    return notes
