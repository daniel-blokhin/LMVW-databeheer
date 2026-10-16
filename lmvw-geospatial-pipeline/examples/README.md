# Synthetic database-ready example

These are generated outputs of `configs/demo.yaml`, not original tender records or live API responses. All identities, geometries, source records and publication text are artificial test fixtures. No original credentials or private source rows are included.

Run `python -m lmvw_pipeline verify-bundle examples/database_ready` from the repository root to check the complete bundle. There are 17 CSV tables with SQL DDL, a JSON contract, load order, hashes and provenance. `quality_summary.json` contains the sample quality results.

Eight input plans are retained: four eligible for enrichment, four quarantined. Input validation finds five ERROR findings and three WARNING findings; two further findings describe unverified/outside DSO candidate associations. There are 35 plan-source relations across the four relation tables. One bad record can have multiple findings.

Generate a fresh result with `python -m lmvw_pipeline run --config configs/demo.yaml`. Business records and relationships are deterministic for the same inputs and settings, but run UUIDs, timestamps and environment metadata intentionally change, so two bundles are not byte-identical.

The example shows a private staging data contract. Actual exported tender data must not be committed just because these artificial example files are safe to share. Read `SECURITY.md` and the data model before implementing a database loader or public dashboard.
