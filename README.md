# LMVW | Housing Data Engineering Pipeline

**Python · REST APIs · Pandas · GeoPandas · Shapely · Data Quality · SQL Server**

A portfolio reconstruction of data engineering work for a Dutch housing-monitoring tender demonstration. The aim is to show how I worked with **API data ingestion, data preparation, Python-based data-quality checks, geospatial joins and database-ready exports**. The pipeline deliberately ends before dashboards and visualisations.

> **Scope:** this is a reproducible technical case study, **not** an official government service or production deployment. All data committed to Git are **synthetic**. The original demo included IO Factory; the quality engine here is an independent Python implementation.

## The problem

Provincial housing plans arrive with attributes (planned capacity, property types and construction phases) and geographical boundaries. National source systems contain complementary data: buildings and residential units in **BAG**, cadastral parcels in **BRK**, and planning documents in **DSO**. Before these datasets can be analysed, the housing-plan delivery must be checked, cleaned *without hiding source errors*, and spatially linked to the external objects.

## What I demonstrate

1. **Extract:** read CSV/Excel housing plans, plus BAG/BRK OGC Features and DSO REST API data (or run with synthetic JSON responses without keys).
2. **Transform:** map Dutch source columns to consistent field names, process date/count fields, and transform geometries between EPSG:28992 and WGS84.
3. **Validate:** execute standalone Python rules for completeness, validity, sums, duplicates, plan status and geometry. Keep rejected source records separately rather than silently correcting them.
4. **Spatially join:** intersect plans with BAG units/buildings and BRK parcels; preserve authoritative BAG unit-to-building relations. DSO geographic API candidates are **not** considered substantively confirmed.
5. **Export:** write normalized **database-ready CSV tables** and matching SQL Server DDL. This project does not insert the tables into a running SQL Server.

```text
        Housing plans (CSV / Excel / polygons)
                          |
                  ingestion.py
                          v
          quality.py  --> DQ issues / quarantine
                          |
                  valid plan geometries
                          |
    BAG API -------+------+------ BRK API
                   |      |
                   + DSO API
                          |
                  geospatial.py
                          |
                  export.py
                          v
             CSV tables + SQL schema
        (dashboard / visualisations: future work)
```

## Quick start: offline, no API key required

Requires **Python 3.11+**. Run the commands from the repository root:

```bash
python -m venv .venv
# Activate .venv for your operating system.
python -m pip install -r requirements.txt
python -m pipeline.run run --config config.yaml
```

The output appears in `data/runs/<run-id>/database_ready/`. For just the data-quality step:

```bash
python -m pipeline.quality --config config.yaml
# Returns exit code 2 when the sample contains rejected records (intentional).
```

Run the tests:

```bash
python -m pip install pytest
python -m pytest -q
```

The `examples/database_ready/` directory also contains a pre-generated **synthetic output example**. Its CSV tables can be inspected directly; `python -m pipeline.run verify examples/database_ready` verifies them against the installed export schema.

## Folder guide

| Location | Why it is here |
|---|---|
| `pipeline/run.py` | The one end-to-end entrypoint: data → DQ → API → spatial joins → export |
| `pipeline/ingestion.py` | Read and normalize incoming housing plans (CSV, Excel, optional GPKG) |
| `pipeline/quality.py` | Standalone Python quality checks and quarantine logic |
| `pipeline/bag.py`, `brk.py`, `dso.py` | The three source-specific data converters |
| `pipeline/http_client.py` | HTTP/API calling, OGC pagination and network safety checks |
| `pipeline/sources.py` | Collect API responses and create consistently structured source records |
| `pipeline/geospatial.py` | Polygon validation, CRS transformations and spatial relationships |
| `pipeline/export.py` | CSV export, table keys, SQL types and export verification |
| `pipeline/settings.py` | Shared small helpers, configuration and runtime-only credentials |
| `config.yaml` | The **single** place for sample paths, column mapping and DQ settings |
| `data/sample/` | Synthetic example inputs and source API response shapes |
| `examples/database_ready/` | Small synthetic example of the final database-ready output |
| `sql/schema.sql` | SQL Server tables to receive the exported CSVs |
| `tests/` | Focused automated tests for DQ, geo joins, exports and API key safety |

The two support modules (`settings.py` and `sources.py`) keep shared parsing and source orchestration out of domain-specific BAG/BRK/DSO code. No frameworks, plugin architecture or multi-environment deployment system are required.

## Main outputs

- `plans.csv`: the original plan records with normalized fields and processing status.
- `dq_issues.csv` and `quarantine.csv`: transparent, traceable data-quality feedback.
- `bag_panden.csv`, `bag_verblijfsobjecten.csv`, `brk_percelen.csv`, `dso_documents.csv`: source-object tables.
- `plan_bag_pand.csv`, `plan_bag_vbo.csv`, `plan_brk_perceel.csv`, `plan_dso.csv`: geographical relation tables.
- Other supporting CSV tables contain construction phases, housing composition, BAG object hierarchy and run status.
- `schema.sql` and `schema.json`: matching SQL Server DDL and field definitions. `manifest.json` records output checksums for reproducible sample verification.

The example produces **8 plans (4 eligible, 4 quarantined)** and **34 BAG/BRK/DSO plan-source links**. It exports 17 relational CSV tables.

The example data contains deliberately invalid records. Errors cause quarantine; missing values are **not** replaced with zero. Not every DSO result is a confirmed relationship. The example uses **BAG, BRK and DSO only**; the old project's extra Ruimtelijkeplannen adapter and replay machinery are intentionally out of scope.

## Live APIs (optional)

Use your **own authorised access**. BAG and BRK are accessed through their PDOK OGC APIs; DSO uses the relevant PRE or production environment. API hosts are restricted, HTTPS and TLS verification are enforced, redirects are refused and API requests have timeouts, limits and bounded retries.

The DSO key is **never committed or passed via a CLI argument**. Use an environment variable matching `DSO_API_KEY_PRODUCTION` (default environment) or `DSO_API_KEY_PRE`. Alternatively, set the matching `*_FILE` variable to an access-controlled file. **Do not paste credentials into `config.yaml`, `.env.example`, notebooks, logs, or the README.** If the old key was ever exposed, revoke and replace it before use.

Place your real delivery in `data/private/` (Git-ignored), then run, for example:

```bash
python -m pipeline.run run --mode live \
  --plans data/private/your_delivery.xlsx \
  --geometries data/private/plans.gpkg \
  --geometry-layer plans
```

The `config.yaml` `sources.dso_environment` defaults to `PRE` for the synthetic case. For live production, change this setting to `PRODUCTION`, then supply the **production** credential. Do not assume the example geometries or IDs match any live locality. A live run depends on external network availability, current API contracts and access permissions; it has **not** been verified against those services in this portfolio release.

## Limits and future work

- **In scope:** demo-sized datasets, Python DQ, BAG/BRK/DSO ingestion, spatial links and SQL Server-ready CSVs.
- **Not demonstrated:** a live production API run, production credentials, actual SQL Server loading, role-based data publication or production security certification.
- **Next step:** import the prepared tables into SQL Server, add analytical queries and create visualisations based on these tables, with separate handling for confidential plans.

**Important:** records labelled confidential are retained in internal staging. This project provides **no public-data endpoint or confidentiality authorisation layer**. Never publish its exports from real deliveries as open data. Read [`NOTICE.md`](NOTICE.md) before reusing or publishing code from the original work project.
