# Database-ready contract

## What “database-ready” means here

The bundle is a validated set of typed CSV tables plus a matching SQL Server schema and load order. It is **not** a database dump, a database connection test or an automatically executed SQL import. All records satisfy the implemented serialization/type/key contract; business-invalid plans are explicitly marked REJECTED and preserved as staging records.

`src/lmvw_pipeline/contracts.py` is the source of truth. `schema.json` documents column names, types, nullability, lengths, primary keys, foreign keys and insertion order. Regenerate committed SQL using:

```bash
python -m lmvw_pipeline schema --output sql/schema.sql
```

The generated DDL targets a new `lmvw` schema in SQL Server. It includes composite PK/FK constraints and does not disable them, drop existing tables or assume auto-increment plan IDs. Execute first-install DDL only against an appropriately prepared database. `GO` is a client batch separator, not a statement for a generic database driver. Optional `analytical_views.sql` is a next-stage internal query example, not executed by the pipeline.

## Tables and grain

| Table | Grain within one run |
|---|---|
| `pipeline_run` | One execution, with mode, status, delivery, timestamps and provenance |
| `source_status` | One source (BAG, BRK, DSO, RP), including disabled/not-queried states |
| `plans` | One original delivery row, including canonical values and raw payload |
| `plan_phasing` | One plan record and original year/year-range bucket |
| `plan_breakdown` | One plan record, category group and category code |
| `quarantine` | One rejected plan record, with original values and input error count |
| `dq_issues` | One deterministic input or enrichment finding |
| `bag_panden` | One native BAG pand |
| `bag_verblijfsobjecten` | One native BAG VBO |
| `bag_vbo_pand` | One authoritative native VBO/pand relationship |
| `brk_percelen` | One BRK namespace/local-ID parcel |
| `dso_documents` | One environment/source-type/native-document identity |
| `dso_document_text` | One unique regulation's extracted full publication text |
| `plan_bag_vbo` | One plan-record/VBO relationship |
| `plan_bag_pand` | One plan-record/pand relationship, with spatial and official-reference evidence |
| `plan_brk_perceel` | One plan-record/parcel positive-area relationship |
| `plan_dso` | One plan-record/document API candidate, including verification state |

All child tables include `run_id`. Join on the complete run-scoped key, not just `Koppelcode`, a native ID or a row number. Same native objects can recur in different runs and belong to multiple plan records. Counts across overlapping plans are therefore not automatically distinct national object counts.

## CSV and SQL values

CSV is UTF-8 without BOM, comma-separated, LF-terminated, with standard quote escaping. Newlines inside publication text are quoted CSV content; a record is not necessarily one physical line. Use a CSV parser, never `split(',')` or line counting.

`\N` is NULL; an empty field is genuine empty text. The literal text `\N` is reserved and rejected. The contract-aware `read_table` reverses this encoding. Counts are BIGINT; flags are BIT encoded `0`/`1`; native BAG identifiers are NVARCHAR(16), not integers. BRK IDs retain namespace and local ID. No leading zeros are reconstructed after being lost upstream.

Text lengths are checked in UTF-16 code units, matching SQL NVARCHAR storage semantics; over-length text blocks export rather than truncating. JSON columns contain complete objects/arrays. Decimals fit DECIMAL(38,12). Timestamps carry explicit offsets and up to six fractional digits in files, with SQL DATETIMEOFFSET(7) preserving that precision. Invalid timestamps/dates/counts in external sources stop normalization.

Geometry is available as validated RD New WKT plus a complete WGS84 GeoJSON geometry object. Numeric coordinate arrays alone are **not** treated as GeoJSON. SQL spatial columns are not generated or indexed automatically; add them in a tested loading migration if needed.

## Future loader contract

A loader should first run `verify_bundle`, verify the intended destination/schema and use `schema.json` load order. Parse rows with `read_table`, translate JSON/text unchanged, `\N` to database NULL through the parser, decimals to `Decimal`, and timestamps to timezone-aware datetime values. Execute parameterized inserts in a transaction. Verify row counts and constraints before committing. Make a repeated `run_id` an explicit no-op/error rather than duplicating data. Do not disable foreign keys to make a broken import succeed.

A database client needs a deliberate import adapter for this NULL convention; a generic “Import CSV” wizard is not guaranteed to interpret it correctly. No undocumented claim of drop-in compatibility with the old `dbo.LMVW_Plan` schema is made. The new schema normalizes phasing and categories and replaces load-order-dependent IDs.

## Safe analytical use later

Select one run explicitly and filter plan `processing_status` to READY/WARNING. Sum capacity at **plan grain**. Aggregate each BAG/BRK/DSO relation table separately before joining totals, or capacity will be multiplied by many-to-many detail rows. Keep source availability/status alongside counts: DISABLED is not a measured zero. Avoid joining full publication text into general dashboard datasets.

`error_count` and `warning_count` on `plans` are input-validation counts. Source-association warnings live in `dq_issues` and `quality_summary.json` and do not retroactively alter the input gate. A production BI model should distinguish these two quality domains.

Every export remains private staging by default, including the complete raw payload and DQ source values. Public disclosure rules and role-based access are separate, unimplemented responsibilities.
