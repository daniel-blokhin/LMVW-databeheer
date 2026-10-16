# LMVW Geospatial Data Pipeline

**From housing-plan deliveries and public APIs to validated, spatially linked database tables.**

A Python data-engineering portfolio project built around a Dutch housing-monitoring case. It demonstrates API integration, data transformation, explicit quality rules, coordinate-system handling, spatial joins and reproducible database-ready exports. The processing is a standalone package: **no IO Factory, notebooks, database connection or dashboard is required**.

The current boundary is a verified export bundle. Interactive maps, dashboards, actual database loading and predictive modelling are later work, not features claimed by this release.

## Run the example

Python 3.11 or newer is required. This revision was tested locally on Python 3.13; the CI matrix targets 3.11, 3.12 and 3.13. Create a virtual environment from the repository root:

```bash
python -m venv .venv
# Linux/macOS
source .venv/bin/activate
# Windows PowerShell, instead of the line above:
# .\.venv\Scripts\Activate.ps1
python -m pip install -e ".[dev]"
python -m pytest -q
python -m lmvw_pipeline run --config configs/demo.yaml
```

The default run is **offline and entirely synthetic**. It exercises the processing and export stages without API keys or paid services. Installation still needs access to the Python package index unless dependencies are already available. The tests additionally exercise the actual HTTP/adapters through controlled simulated responses; they do not make live requests.

The command prints its run directory and produces:

```text
data/runs/<run_id>/
  run_context.json              # stage status, input/code/rule hashes, environment versions
  validation/
    summary.json                # evaluated, passed, failed and unevaluable checks
    issues.json                 # record-level findings
    quarantine.json             # rejected records and their unchanged raw values
    plans.json                  # canonical input-validation result
  raw/                          # private JSON response cache, only for live calls
  quality_summary.json          # quality, source status and relation counts
  database_ready/
    *.csv                       # 17 typed staging/source/relation tables
    schema.sql                  # SQL Server first-install DDL with PKs and FKs
    schema.json                 # machine-readable data contract and load order
    manifest.json               # row counts, hashes and provenance
```

Generated runs are ignored by Git. A small, already generated synthetic bundle is included in [`examples/database_ready`](examples/database_ready). Verify it immediately:

```bash
python -m lmvw_pipeline verify-bundle examples/database_ready
```

### What the sample proves

Eight input records remain eight distinct plan records. Four pass the quality gate, four are quarantined. The sample intentionally contains a wrong category total, an unknown confidentiality label, an invalid polygon and a non-numeric capacity. Two valid records share one area key without being merged. A negative **net** capacity is valid when demolition exceeds additions.

The spatial example includes a point exactly on a plan boundary, overlapping parcels, a building outside the query area linked through an official BAG VBO/pand relation, a shared DSO regulation and DSO candidates without verified overlap. Repeated publication clauses are preserved. These are designed test cases, not real housing statistics.

## The pipeline

```text
Excel/CSV plans + GeoPackage or declared-CRS WKT
                 |
       Intake + stable delivery/record identifiers
                 |
       Python quality gate -----------------> Quarantine + issues
                 |
         Accepted plan geometries
                 |
  BAG / BRK OGC APIs + DSO Presenteren/Geometry + optional RP
                 |
   Typed source objects + official BAG parent relations
                 |
  RD New spatial matching + explicit evidence classification
                 |
       CSV contracts + SQL schema + manifest
                 |
       Future database and visualisation layer
```

The run preserves raw business values and lineage while exposing canonical fields. Invalid business values are not quietly repaired; missing values are not converted to zero. A failed API request, ambiguous parent lookup, conflicting source duplicate or incomplete pagination blocks a successful bundle rather than fabricating an empty source.

## Source modes

| Mode | Purpose | Network and credentials |
|---|---|---|
| `fixtures` | Public, synthetic demonstration | No network or keys |
| `live` | Query the real configured source services | Network; DSO/RP credentials when enabled |
| `replay` | Reprocess a completed live run's recorded responses | No network or keys; missing/tampered cache is an error |
| `snapshots` | Migrate the original private BAG/BRK source CSVs | No network or keys; DSO/RP disabled because no response snapshots were supplied |

The supplied adapters implement BAG pand/VBO extraction and authoritative parent resolution; BRK cadastral-map parcels; DSO regulations and environmental permits; DSO geometry retrieval; regulation document text; and optional Ruimtelijkeplannen documents. An API candidate is **not** a confirmed planning milestone, legal conclusion or proof of realised dwellings. BRK map geometry does not provide ownership information.

Live requests use explicitly bounded scopes, pagination, timeouts, retries and source-specific HTTPS destinations. Current endpoints and design references are documented in [`docs/sources.md`](docs/sources.md). Live provider responses and SQL Server execution have **not** been verified from the build environment; see the evidence boundaries in [`docs/validation_evidence.md`](docs/validation_evidence.md).

## Standalone data quality

```bash
python -m lmvw_pipeline validate --config configs/demo.yaml
```

This command stops after Python validation. It does not resolve API keys or call external sources. It exits with code `2` when records are rejected; the diagnostic files are still written. A full `run` normally exits `0` after a complete staging export even when some input records are quarantined. Add `--fail-on-dq` to use the same exit-`2` policy in automation. An operational failure exits `1` and does not produce a successful export.

Rules cover schema mapping, required fields, Excel formula caches, numeric types, missing counts, confidentiality, categories, duplicates, capacity arithmetic, category totals, phasing, geometry and source-association evidence. Their meaning and limitations are in [`docs/data_quality.md`](docs/data_quality.md). This is a newly implemented, versioned Python rule set, **not a certified reproduction of an unavailable IO Factory flow**.

## Use your original files

Do not copy the original ZIP into the repository. The migration helper extracts only the relevant private inputs and latest-scope source CSVs; it never executes notebooks or copies their keys:

```bash
python scripts/import_legacy_data.py --archive "/path/to/LMVW Databeheer tender 1.zip"
python -m lmvw_pipeline run --config configs/snapshots.example.yaml
```

For live requests, first read [`SECURITY.md`](SECURITY.md), rotate any exposed credentials and inspect the source scope. Copy `configs/live.example.yaml` to `configs/my.local.yaml`, configure your local input paths and enable only required sources. Then use an injected runtime environment/secret file, or the hidden-input helper:

```bash
python scripts/run_live.py --config configs/my.local.yaml
```

No API key belongs in YAML, source code, a notebook, a CLI argument or Git. `.env.example` is documentation and is **not automatically loaded**. PRE and production are explicit and separate. The optional RP adapter uses a distinct credential variable. See [`docs/migration.md`](docs/migration.md) for the full workflow, including replay.

## Repository layout

```text
src/lmvw_pipeline/
  adapters/        # BAG, BRK, DSO/RP, OGC paging and source-mode selection
  validation/      # standalone quality engine
  intake.py        # source delivery parsing and identity
  geometry.py      # CRS validation and bounded query scopes
  matching.py      # spatial and official-reference joins
  http.py          # source-scoped transport, redacted failures and replay
  secrets.py       # runtime-only secret loading
  contracts.py     # table definitions and generated SQL DDL
  exporting.py     # typed CSV round-trip and referential checks
  pipeline.py      # orchestration, stages and provenance
  cli.py           # run, validate, verify-bundle, schema
configs/           # separate mappings, rules and source modes
tests/             # isolated unit, transport/security and integration tests
sql/               # schema and optional internal analytical views
scripts/           # sample generation, private migration and repository checks
docs/              # architecture, contracts, decisions, security and roadmap
examples/          # verified synthetic output only
.github/           # offline CI and dependency-update configuration
```

## Important design decisions

**Record identity is not an area key.** `record_id` hashes delivery identity, worksheet and source row. A changed file or row order means a new delivery/record version. This is reliable within a delivery, not a longitudinal business-plan identity solution. `run_id` separates processing executions. Native BAG IDs remain 16-character strings; BRK keys retain namespace plus local ID.

**Spatial association is evidence, not causation.** VBO points on boundaries are included; polygon links require positive overlap above the configured threshold. BAG parent relations can justify a building outside the plan. DSO search candidates, spatial verification and substantive confirmation remain separate fields. Substantive confirmation defaults to `false`.

**Staging is not publication.** Database-ready files contain private plan records, raw payloads and DQ details. They are not filtered public exports and do not implement user authorisation. An unknown confidentiality label is rejected. The optional SQL views are internal analysis examples, not a security boundary.

**One contract, not loose CSV conventions.** Export files use ordered columns, UTF-8, comma delimiters, standard CSV quoting and `\N` for NULL. Empty text is different from NULL. All PKs, FKs, SQL types, lengths and row counts are checked before and after export. Full publication text is kept out of lightweight plan/document joins. See [`docs/data_model.md`](docs/data_model.md).

## Scope, evidence and next work

The code was exercised with synthetic fixtures, mocked live HTTP followed by offline replay, and the supplied private plan/geometry/BAG/BRK files. Private input records and caches are not distributed. The committed CI workflow is ready to run after pushing to GitHub; its Linux/Windows matrix is not a claim that hosted CI has already run.

There is no deployed SQL Server loader, web application, dashboard, authentication service, historical entity resolution, CBS ingestion, WOBI integration, trained ML model or complete national-scale execution benchmark in this version. These are deliberate boundaries, not hidden placeholders. [`docs/next_steps.md`](docs/next_steps.md) explains how to add the database and visual layer without changing the core pipeline.

Before publication, review code ownership and reuse rights with the relevant rights holders. No open-source licence has been assigned automatically; see [`NOTICE.md`](NOTICE.md). Initial publication should remain private until that review is complete.
