# Refactoring audit and decisions

## Material reviewed

The supplied archives contained thirteen notebooks in total, one standalone DSO helper script, SQL fragments, plan/source datasets and hundreds of cached JSON files. Multiple notebook versions covered similar BAG/BRK extraction, geometry normalization and plan matching. The DSO archive contained implementation code but no complete DSO response snapshot set suitable for a data regression run.

Original tender documents and project descriptions were used only as context. They are not bundled with this portfolio. No private source rows, cached production payloads, notebook outputs or original key values are published here.

## Preserved technical intent

| Original capability | Refactored location |
|---|---|
| Read LMVW plan lists and attach polygons | `intake.py`, `validation/engine.py`, configured source mapping |
| BAG/BRK buffered geographic extraction | `geometry.query_scope`, `adapters/ogc.py`, `adapters/collect.py` |
| BAG native-ID and parent-reference handling | `adapters/bag.py` and normalized `bag_vbo_pand` |
| BRK namespace/local-ID parcel normalization | `adapters/brk.py` |
| DSO regulation/permit/RP lookup | `adapters/dso.py` and explicit source modes |
| DSO geometry and publication text retrieval | unique document/geometry enrichment in `adapters/dso.py` |
| Plan/source relation generation | `matching.py`, with stable record keys rather than database load order |
| Database import CSVs and table declarations | `contracts.py`, `exporting.py`, generated `sql/schema.sql` |
| Demo quality-control requirements | newly implemented standalone Python rule engine |

This is a functional redesign of the raw scripts, not an archive of notebooks wrapped in a command-line facade. The code is organized by responsibility and receives explicit inputs rather than relying on cells run in a specific order or global workstation paths.

## Deliberate departures from the demo

Hardcoded credentials and default key literals are removed; secret handling is runtime-only and source-scoped. Broad exception suppression is replaced with controlled failures. Unsafe SQL string-template inserts are not part of the pipeline. Source IDs remain strings and real composite keys are validated.

The old demo's `LMVW_Plan_ID` depended on database insertion order. New relations use the delivery/record key, while run IDs allow distinct executions to coexist. A shared `Koppelcode` is flagged as an area-key reuse, not incorrectly enforced as a unique plan ID. Old precomputed relation CSVs are not trusted as migration inputs.

Exact source duplicates are collapsed only when the source payload agrees; conflicts stop processing. Exact duplicate input plan rows remain visible and are quarantined rather than silently dropped. Missing values are not forced to zero. Incorrect business sums are not corrected to make the dashboard look consistent.

GeoJSON remains a complete geometry object, rather than a string with its type wrapper removed for one dashboard component. RD coordinates are used for areas; WGS84 is an explicit presentation representation. Empty/invalid geometries and unsupported dimensions are rejected instead of being repaired with an undocumented `buffer(0)`.

DSO search candidates, local geometric verification and substantive confirmation are separate. A broad municipality-wide regulation does not prove plan-specific legal applicability. The text step runs once per unique regulation and preserves repeated legal clauses. Full text is separated from document metadata to avoid multiplying large strings across plan joins.

The quality engine is new code because the executable IO Factory flow was not supplied. Its default rules and thresholds are documented and tested; they are not asserted to be byte-for-byte or outcome-identical to the old demo.

## Excluded, rather than pretended implemented

The original materials include CBS SQL table fragments but no complete CBS ingestion path. A separate WOBI worksheet is present without an established canonical join and validation contract for this refactor. Both require explicit future integrations. IO Factory email/report/upload flows, BI visuals, access-control implementation, historical plan identity and production operation remain outside the current output boundary.

Source API adapters are implemented and tested with controlled responses, but live provider access was not available during construction. A real small-scope smoke test and SQL Server load integration test remain release gates for deployment. The repository does not claim national-scale performance, compliance certification or a predictive model.
