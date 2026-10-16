# Architecture and execution model

## Design goal

Transform delivery-specific demo scripts into an inspectable, locally runnable data pipeline. The essential skills are explicit API consumption, reliable parsing, quality control, geospatial integration and clean downstream contracts. The design avoids a distributed orchestrator, database server, web framework or notebook state because none is necessary for the present boundary.

`pipeline.run_pipeline` orchestrates stages; adapters do not write SQL, quality rules do not call APIs, and matching operates on canonical records rather than source-specific payloads. `contracts.py` drives both SQL DDL and export validation. Configuration separates business-field mapping, rule policy, source selection and operational limits.

## Stages and invariants

**Intake.** Read the specified worksheet or explicitly delimited CSV. Excel cached results are read alongside formula expressions; missing caches are not silently accepted as evaluated formulas. Geometry may come from a GeoPackage with a declared CRS and unique area keys, or WKT plus a per-record `CRS` column. Input hashes are checked around reading to detect concurrent changes. Geometry-file ambiguity blocks the delivery rather than guessing or dissolving features.

**Identity.** A delivery hash incorporates the plan-file hash, geometry-file hash and worksheet. A record hash incorporates delivery, worksheet and source row. A separate raw-record hash supports exact-duplicate detection. Every execution has a fresh UUID `run_id`. None of these technical keys pretends to solve business-plan continuity across resubmissions.

**Quality.** Validate all source records before enrichment. Every row remains in the canonical staging result; ERROR records additionally appear in quarantine. Errors do not mean loss of source evidence. WARNINGS remain usable according to the configured gate. The default enrichment gate excludes ERROR records and unusable geometries. An explicit `include_rejected_plans` option exists for diagnostics and is recorded in provenance; it is not the recommended publication/analysis path.

**Scope and API extraction.** Use accepted plan polygons in RD New, union them, buffer the union, and enumerate bounded query tiles. Request the RD CRS and apply an exact local intersection after bbox selection. PAGINATION safety limits and inconsistent counts raise a source error. BAG/BRK responses without a Content-Crs confirmation are explicitly noted in source status; the requested RD CRS and local bounds remain in force. Incorrect declared CRS is rejected.

**Normalisation.** Strictly parse native identifiers, counts, dates and geometry. Identical source objects returned by overlapping tiles are deduplicated. Different content for the same native key within a run blocks export. For BAG, preserve authoritative VBO-to-pand references; query missing parents explicitly, even outside the scope. No nearest-building guess is used.

**DSO enrichment.** Group identical plan geometries for API lookup while retaining every plan-record relationship. Collect unique regulation, permit and optional RP documents. Cache unique geometry lookups and fetch each regulation's document text once. PRE, production and synthetic sources have distinct document identities. Preserve repeated clauses and extract plain text, without executing HTML. Preserve unverified/outside candidates as evidence states rather than quietly dropping them or calling them confirmed.

**Matching.** Build STRtree spatial indexes. VBO point boundaries are included. Pand/BRK polygon relationships require positive area above the threshold; touching boundaries alone do not create these area relationships. Authoritative BAG references can independently create a pand relation, whose spatial evidence remains separate. BRK overlap percentages use geometric area, not the registered cadastral-area attribute.

**Export.** Check the full table set, column names, SQL types, UTF-16 text lengths, keys and referential integrity. Write all outputs into a temporary run-local directory. Read the CSVs back with explicit types, validate them again, write checksums and promote the directory only when the bundle verifies. A source failure leaves the validation diagnostics and a failed run context, not a success manifest.

## Reproducibility is scoped

Fixed inputs, rule/mapping files and source fixtures produce identical business records. Different executions intentionally have different run IDs/timestamps. A new live request is not guaranteed to reproduce an earlier public-register state. The pipeline records versions, source/input/config/rule/code hashes and the DSO temporal query instant. It does not claim that separate public APIs form one globally atomic snapshot.

Replay requires a completed live run, identical delivery and rule/mapping hashes, and all matching response fingerprints. It reuses the original DSO time parameters. Replay never falls back to the network; a missing or corrupted response is a failure. Cache fingerprints/checksums detect accidental changes, not a malicious actor able to replace both payloads and hashes. Raw caches and run directories remain private operator-controlled storage.

## Operational limits

This is a bounded single-process batch pipeline. Source records, geometries and document text are held in memory; national-scale throughput, distributed processing, automated scheduling, encrypted storage, monitoring alerts and recovery from partially completed runs are not implemented. Limits prevent accidental unbounded queries but are not a guarantee of a specific memory ceiling. A failed run is retained for diagnosis and can be rerun with corrected input/configuration. Avoid parallel processes writing to the same manually selected cache location.

Requests use fixed HTTPS services, bounded retries and delays. Larger production scopes need provider-approved usage limits, backpressure, partitioning, streaming storage and performance measurements. These are more useful next steps than adding unnecessary orchestration tooling merely for a portfolio label.
