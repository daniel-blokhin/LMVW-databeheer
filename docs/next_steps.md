# Next phase: from verified tables to analysis and visualisation

## First: validate real deployment assumptions

Complete credential rotation and a small, approved live API test. Confirm provider payloads, geometry CRS, pagination, time parameters and record counts against official responses. Keep a redacted test fixture for every schema variant actually encountered. Test the generated DDL and a parameterized loader against the intended SQL Server version in a transaction. Do not treat an offline green test suite as proof of these external integrations.

Add a reproducible environment lock and dependency vulnerability scan in the chosen development/CI environment. The current pyproject specifies version ranges to permit compatible updates; `docs/tested_environment.json` records the environment actually used, not a universal dependency lock. Review code/data reuse rights before making the repository public.

## Visual layer: use the current output, not new extraction notebooks

Start with one selected run and a reusable read/query adapter. The visual layer should consume `plans`, `plan_phasing`, `plan_breakdown` and relation tables or corresponding internal SQL views. It should not contain API keys or repeat ingestion/cleaning logic. Preserve explicit source availability and input-quality statuses in the UI.

Recommended first views are a plan-level quality overview, capacity split by municipality and hard/soft status, original phasing buckets, and a plan map with separate BAG/BRK/DSO evidence layers. Show DSO verification state and source environment; do not label all candidates as confirmed documents. Keep the raw regulation text behind an on-demand detail view rather than joining it into every chart row.

Capacity charts must aggregate at plan-record grain. Source object counts require their own groupings, since the same building, parcel or document may belong to multiple plans. Do not manufacture annual values by dividing a five-year bucket, call existing BAG objects “newly realised houses,” or infer ownership from cadastral-map polygons.

Build an internal analytical UI first. A public view additionally needs approved confidentiality, aggregation/suppression and authorisation behaviour. These policies belong in a tested publication service, not only in chart filters. Do not expose `raw_payload_json`, quarantine records or private source values in a public dashboard.

## Further integrations

CBS public municipality-level statistics can be added as a source adapter with explicit time/geography/measure grain and missing-value semantics. Do not misrepresent a municipality total as plan-level observations. WOBI requires a documented identity bridge before joins. Historical plan identity requires deliberate matching/versioning decisions beyond hashes of source deliveries.

Only add machine learning after a meaningful target, labelled outcomes and leakage-safe temporal evaluation are available. Current geographic association and rule-based validation are not ML. An Airflow/Dagster deployment, streaming store or distributed spatial processing should follow actual scheduling/scale needs, not substitute for tested data contracts.
