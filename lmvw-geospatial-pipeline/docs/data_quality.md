# Python data-quality rules

## Execution and policy

`validation.validate_delivery` is deterministic and has no external I/O after input has been parsed. `lmvw validate` executes it as a standalone stage without any API credentials or IO Factory. Rule policy lives in `configs/quality.yaml`; field mapping lives in `configs/columns.yaml`. Both files are hashed into run provenance.

A failed check yields a deterministic issue ID, record ID, source row, rule ID, category, severity, field, original/source value and message. Rule summaries separately count evaluated/passed/failed and not-evaluable checks. A sum that cannot be calculated because an input is missing is not reported as “passed.” One bad field can legitimately trigger a type finding, a completeness finding and a required-core-field finding; issue counts are not counts of unique bad records.

Every input row remains in `plans`. One or more ERRORs produce REJECTED plus a quarantine record. WARNINGs alone produce WARNING; otherwise the record is READY. Default enrichment excludes REJECTED rows. Canonical numeric values are parsed losslessly where possible; failed conversions become NULL with the raw input retained. Raw business numbers are not silently corrected to force agreement.

This rule set is a portfolio implementation guided by supplied source columns and the case's documented concepts. No executable export of the original IO Factory quality flow was supplied. Rule equivalence, formal Basisset certification, and approval by an LMVW governance body are not claimed.

## Implemented catalogue

| ID | Default | Meaning |
|---|---|---|
| DQ-XLSX-001 | ERROR | An Excel formula has no cached result; the workbook must be recalculated by its producer |
| DQ-TYPE-001 | ERROR | A supplied count is not an exact finite SQL BIGINT-compatible integer |
| DQ-COM-001 | ERROR | Required municipality, plan name, area key, plan type or plan status is missing |
| DQ-COM-002 | WARNING | A numeric field is missing/unparseable; do not replace with zero |
| DQ-COM-003 | ERROR | Gross capacity or demolition is missing/unparseable, blocking usable capacity metrics |
| DQ-CONF-001 | ERROR | Confidentiality is not an explicit Ja/Nee; unknown never defaults to public |
| DQ-RANGE-001 | ERROR | A count other than reported net capacity is negative |
| DQ-RANGE-002 | ERROR | Temporary housing exceeds gross capacity |
| DQ-RANGE-003 | ERROR | The supplied disjoint senior-housing categories exceed gross capacity |
| DQ-CAT-001 | ERROR | Plan status falls outside the configured monitoring categories |
| DQ-CAT-002 | ERROR | Dominant plan type is unrecognised |
| DQ-DUP-001 | WARNING | An area key is shared; retain separate source records |
| DQ-DUP-002 | ERROR | An exact raw source row is duplicated; retain and flag, do not automatically merge/delete |
| DQ-NET-001 | ERROR | Reported net capacity differs from gross minus demolition, when all are evaluable |
| DQ-SUM-001 | ERROR | Housing-type categories do not sum to gross capacity |
| DQ-SUM-002 | ERROR | Tenure/price categories do not sum to gross capacity |
| DQ-SUM-003 | ERROR | Original year/year-range phasing buckets do not sum to gross capacity |
| DQ-GEO-001 | ERROR | Plan has no usable polygon/multipolygon in an explicitly declared CRS |
| DQ-LINK-001 | WARNING | A DSO/RP API candidate lacks locally verified positive-area overlap; added after enrichment |

Schema-level failures, invalid/overlapping phasing headers, missing source files or ambiguous GeoPackage area keys fail the delivery rather than manufacture per-row validity. External-source contract violations, incomplete API pagination and orphan source relations block the bundle as operational/data-contract errors.

## Domain decisions that matter

**Negative net capacity is permitted.** A plan with two additions and five removals has net capacity -3. Non-negative constraints apply to underlying counts, not to their difference. Reported and independently calculated net capacity are both retained.

**Blank is not zero.** Optional unknown breakdown or phasing counts remain NULL and create completeness warnings; related sums become unevaluable. Core gross capacity and demolition are required. A missing reported net capacity can remain NULL while calculated net capacity is still derived from valid components; the missing reported value remains visible as a warning. Tighten the appropriate severity/policy only after agreeing its business meaning.

**Area keys are not unique plan identifiers.** Shared geometries can represent separate phases/records. Exact identical rows are a different case. No fuzzy-name matching or automatic deduplication across deliveries is performed.

**Senior categories follow the supplied delivery columns.** The headers describe mutually exclusive non-clustered, clustered non-care, clustered care and other senior forms. The check sums these disjoint categories. It is not a direct validator for a different input that uses nested totals such as total step-free, of which clustered, of which care-suitable. Such an input requires a separate mapping and rule design.

**Phasing preserves uncertainty.** The first ten annual columns and later multi-year buckets can be recognized dynamically from headers. A five-year quantity is not divided equally into years. Overlaps are rejected. This version does not enforce every possible annual reporting-horizon policy, historical movement rule or price-boundary definition.

**Geometry is not repaired silently.** Invalid rings, missing CRS, unsupported dimension/type or out-of-range RD coordinates are rejected. The geographic domain is the European Netherlands. A supplied projected CRS can be transformed explicitly using `always_xy`; metric intersections are computed in RD New, never square degrees.

**Source statuses are not housing outcomes.** A VBO appearing inside a plan does not prove that the planned dwellings have been realised, and a document overlapping a plan does not prove legal/semantic applicability. Every DSO candidate retains `substantively_confirmed = false` in this release.

## Extending a rule

Add a focused check with a stable ID, controlled message, severity and unit tests. Include an unevaluable branch when dependent values may be missing. Bump `quality.yaml`'s version for semantic changes and update this catalogue. Record changes to expected outcomes; do not loosen constraints merely to make a demo look clean. A severity override changes policy, not source truth, and needs review before reuse on real data.
