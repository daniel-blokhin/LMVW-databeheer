# Validation evidence and limits

Build verification date: 16 October 2026. Results below were measured locally, not inferred from the presence of test files. The observed environment is CPython 3.13.5 on Linux; exact dependency and native geospatial library versions are in `tested_environment.json`. This file is evidence for this delivered revision, not an evergreen claim about later changes.

## Automated verification

`python -m coverage run --source=lmvw_pipeline -m pytest -q` completed with **110 passed**. `python -m coverage report --fail-under=85` reported **89% line coverage** (1612 of 1802 statements; 190 missed). This is line coverage, not branch coverage or proof of correctness. Compilation of package and helper scripts also passed.

Tests include lossless count parsing, missing/formula-cache inputs, raw-row conservation, duplicate area versus duplicate record semantics, invalid CRS and two-dimensional geometry enforcement, point-on-boundary rules, positive-area parcel matching, official BAG parent references, DSO evidence flags, publication-text preservation, PK/FK/type contracts, null/empty-text distinctions, Unicode and multiline CSV round-trips, bounded pagination, key/header isolation, destination restrictions, redirect rejection, controlled retry/failure behavior, and cache tamper/missing-response errors.

A simulated live integration test exercises the real HTTP clients and source adapters through mocked responses, writes the actual response cache, then executes offline replay with external networking blocked. It is not a live DSO provider test. Offline fixture mode exercises all processing, linkage and export stages without keys.

## Supplied private input run

The original plan list, GeoPackage and selected BAG/BRK source CSVs were processed end to end in `snapshots` mode. The allowlisted original-archive importer was also exercised against the supplied archive; all six extracted input hashes matched the reviewed files. No notebooks or original credentials were executed or used.

| Measurement | Result |
|---|---:|
| Input plan records retained | 153 |
| Eligible/accepted plan records | 148 |
| Quarantined plan records | 5 |
| Input ERROR findings | 12 |
| Input WARNING findings | 3 |
| Plan-to-BAG VBO relations | 16,174 |
| Plan-to-BAG pand relations | 2,416 |
| Plan-to-BRK parcel relations | 1,512 |
| Total plan-source relations | 20,102 |
| Typed exported CSV tables | 17 |

These are results of the newly implemented rules and configured query scope, not a claim of equivalence to the old demo or independent business truth. Five rejected records are not fifteen rejected records: one row may have several findings. Source snapshots are spatially filtered, so source-table counts can be lower than the original input CSV counts. Native objects can belong to more than one plan.

DSO and RP were explicitly **DISABLED** in this private-snapshot run. Their empty output tables do not mean there were no relevant legal documents. Original DSO response snapshots were not supplied, so no private real-data DSO regression result is claimed. The private outputs and input records are deliberately excluded from this repository; only aggregate verification counts are recorded here.

## Included synthetic result

`examples/database_ready` contains a verified 17-table export produced by the package. Eight plan records remain eight records: four pass the gate and four are quarantined. Five input ERRORs, three input WARNINGs and two enrichment WARNINGs produce ten rows in `dq_issues`. Four eligible plan records produce 35 source relationships. These are intentionally constructed test cases.

The bundle checker re-reads CSV files and checks the contract, column order, SQL types/lengths, NULL conventions, primary keys, foreign keys, row counts and SHA-256 manifest. Hashes detect accidental changes; they do not establish trusted provenance if an attacker can replace both files and manifest.

## What was not executed or certified

No requests were made to real BAG, BRK, DSO or RP services from this build environment. The adapters are implemented and provider documentation was reviewed, but valid replacement credentials and an external network are needed for a real small-scope smoke test. Live success, completeness across every provider document subtype and national-scale reliability remain unproven.

SQL DDL and CSV contracts were checked in Python; a Microsoft SQL Server instance was not available for executing DDL or a transactional import. The included CI matrix is configured for Linux Python 3.11/3.12/3.13 and Windows Python 3.12; hosted GitHub Actions and Windows execution have not yet run. Dependency versions were recorded but no online dependency vulnerability audit, penetration test, external security review, formal Basisset conformance test, legal publication review or compliance certification was performed.

The repository hygiene checker and exact original-key exclusion scan are useful controls, not a guarantee that arbitrary future changes cannot expose secrets. Credential revocation, deployment permissions, encrypted storage, retention, access control and rights-holder approval remain operational responsibilities.

## Reproduce

```bash
python -m pip install -e ".[dev]"
python -m coverage run --source=lmvw_pipeline -m pytest -q
python -m coverage report --fail-under=85
python scripts/check_repository.py
python -m lmvw_pipeline verify-bundle examples/database_ready
python -m lmvw_pipeline run --config configs/demo.yaml
```

For the private test, follow `docs/migration.md` with your original archive. The synthetic sample's intentional quarantine is a successful staging demonstration, not an operational failure. `validate` and `run --fail-on-dq` return exit code 2 for those same rejected records.
