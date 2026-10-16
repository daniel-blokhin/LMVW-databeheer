# Part 2 - LMVW data analytics report

A small reporting layer on top of Part 1's database-ready exports. It demonstrates analytical judgement, housing-capacity indicators, geospatial exploration, data-quality interpretation and communication of findings. No INKIS, IO Factory, database server, external map provider or API key is required.

![Synthetic report](demo/preview.png)

## Install without restructuring Part 1

Extract the ZIP **into the existing repository root**, for example:

```text
C:\VS files\LMVW-databeheer\
```

After extraction, this file must be at:

```text
C:\VS files\LMVW-databeheer\analytics\README.md
```

The ZIP adds only `analytics/` and `PROJECT_OVERVIEW.md`. It does not contain replacements for `pipeline/`, `src/`, the root README, the root configuration, input data or `.git/`. Do not extract it inside `pipeline/` or create another nested `LMVW-databeheer/` folder.

## Start with the finished report

Open `analytics/demo/report.html` in a browser. It is already generated and contains its own Plotly JavaScript. It works without Python or internet access. This is a report of a fixed data selection: charts support hover/zoom and map layers support legend toggles. It is not a client-side replica of the app's dataset filters.

The report contains three sections:

| Section | Analytical question | Content |
| --- | --- | --- |
| Portfolio | How much capacity is planned, and how is it distributed? | Accepted/rejected records, gross/net capacity, municipality, hard/soft status, phasing, housing type and tenure/price categories |
| Maps | Which source objects are actually linked to a plan? | Overall plan contours, detail map, BAG buildings/VBO points, BRK parcels, DSO evidence, source identifiers and match methods |
| Data quality | Which records or source relationships require review? | Processing status, rule-level findings, distinct records, source coverage, candidate versus spatially verified DSO relations |

These are **vector maps in the Dutch RD coordinate system (EPSG:28992)**. They are deliberately not street/satellite maps. The axes have an equal metre scale. Polygon parts and holes are retained as outlines, and a detail-map button switches between the plan neighbourhood and all linked objects. No external tile requests expose the viewed location.

## Optional local app

Use the same virtual environment as Part 1, or create a separate one. From the repository root:

```powershell
python -m pip install -r analytics/requirements.txt
python -m streamlit run analytics/app.py --server.address 127.0.0.1 --browser.gatherUsageStats false
```

The app adds municipality and hard/soft filters, a selectable plan detail, source-object tables, quality drill-down and an HTML download. The default dataset is the separate 36-plan synthetic demonstration. An empty filter selection means zero records; it does not silently switch to all records.

### Your own pipeline export

Run Part 1 first. Point the report at **one complete `database_ready` folder**, not the raw `plans.csv`. For PowerShell:

```powershell
$env:LMVW_BUNDLE_DIR = 'C:\VS files\LMVW-databeheer\data\runs\YOUR_RUN_ID\database_ready'
python -m streamlit run analytics/app.py --server.address 127.0.0.1 --browser.gatherUsageStats false
```

Select the local export and acknowledge authorised local use. To return to the default demo:

```powershell
Remove-Item Env:LMVW_BUNDLE_DIR
```

This checkbox is a reminder, **not access control**. The app does not implement user authentication, confidentiality aggregation or the LMVW publication protocol. Do not deploy it publicly with real data. Unknown/confidential plan records and quality messages can be sensitive. Source mode `fixtures` describes the external sources; it does not prove that the plan input is synthetic or publishable.

### Generate a report without Streamlit

The HTML generator only needs Pandas, Shapely and Plotly. From the root:

```powershell
python -m analytics.report --output analytics/output/my_report.html

python -m analytics.report --bundle 'data/runs/YOUR_RUN_ID/database_ready' --output analytics/output/internal_report.html

python -m analytics.report --municipality 'Demo Waterdam' --output analytics/output/waterdam.html
```

An optional `--record-id` chooses the detail map's plan. The default is the first accepted source row. Existing report files are not overwritten: choose a new output filename or remove your old report deliberately. Generated real-data reports belong in ignored `analytics/output/`, not in `demo/`.

## Read the code in this order

```text
analytics/
  data.py             Load one run, select the population, calculate metrics and joins
  charts.py           Shared charts and RD vector-map layers
  report.py           Independent HTML report and CLI
  app.py              Optional Streamlit presentation and interactive filters
  prepare_input.py    One-off raw CSV/CRS helper for the current intake problem
  make_demo.py        Recreate the synthetic demonstration through Part 1
  tests/              Metric, integrity, geometry, helper and optional UI tests
  demo/               Synthetic input, exact exported bundle, ready-made report, preview
  output/             Local generated reports; ignored by Git
```

`data.py` does not import the engineering package. The same reporting layer can read the supplied original and simplified export versions. `make_demo.py` is the only optional script that imports `pipeline/`; rebuilding the demo requires the simplified Part 1 and its dependencies.

## Metric definitions that prevent misleading results

**Population.** A plan is an exported record identified by `(run_id, record_id)`. A repeated Koppelcode does not imply a duplicate record. READY and WARNING are accepted; REJECTED remains visible in DQ but is excluded from capacity calculations. Report labels deliberately say planrecords rather than claiming business-entity deduplication.

**Capacity.** Gross capacity and demolition are summed at plan-record grain. Net capacity uses `net_capacity_calculated` from Part 1. A negative net is allowed. Empty/all-unknown data is `n.v.t.`, not a measured zero. No plan capacity is summed after a source-object join.

**Phasing and categories.** Five-year buckets remain five-year totals. Missing values are not imputed and are counted beside the sums of known values. The category `unknown` and a missing count are different. Price segments follow the source labels; this layer does not reinterpret legal price thresholds.

**Sources.** A source object shared by two plans counts once in a distinct-object total and twice in a relationship total. Coverage means an accepted plan has a relation, not that the source has proved construction progress. NOT_QUERIED/DISABLED is unavailable, not zero measured coverage. DSO source coverage includes candidates; evidence status is shown separately. An official BAG parent can sit outside the plan contour, so the maps use exported relationship tables rather than recomputing a naive intersection.

**Quality.** One record can have several findings. The synthetic bundle contains 11 plan-validation findings plus 14 link warnings, hence 25 rows in `dq_issues.csv`. Planless source findings, when present, are shown separately in the app and do not belong to a municipality-specific count.

**Integrity and privacy.** The reader checks checksums of the fixed filenames it consumes, run IDs, required columns, types and relationship references. It loads no raw quarantine payloads, raw source values or full publication texts. It does not replace Part 1's complete contract verifier.

## Why your 153 real records were rejected

The supplied simplified engine in `pipeline/quality.py` uses this logic when no geometry file is configured:

```python
geometry_value = raw.get("Polygon_WKT")
crs = text(raw.get("CRS"))
```

Your pasted header includes `Polygon_WKT` and `Polygon_WKT_4326`, but **not `CRS`**. The engine will not guess a CRS, and it does not automatically select the second geometry column. This produces `DQ-GEO-001` for each such record. The example row from the question was reproduced with the existing engine: without CRS it was REJECTED on this rule; after explicitly adding EPSG:28992 it was READY with no findings. No housing values were changed.

That reproduces the provided example, not all 153 local rows. Check your run's actual findings to confirm the total and identify remaining errors:

```powershell
$run = 'data\runs\110dc49e-b2a7-4c67-a570-46381198fd7e'
Get-Content "$run\validation\issues.json" -Raw |
  ConvertFrom-Json |
  Group-Object rule_id |
  Select-Object Name, Count
```

`COMPLETE_WITH_REJECTIONS` means that the processing and staging export completed with quarantined records, **not** that the input passed quality validation. With no eligible plans, source retrieval is NOT_QUERIED and relationships stay empty.

### Prepare a separate private input copy

Put real data in `data/private/plans_raw.csv`, not in tracked sample data. Confirm the CRS using the source specification. The RD coordinates in the provided first geometry correspond to the supplied WGS84 geometry, but this alone is not proof that every row in an arbitrary file uses the same CRS.

For an RD `Polygon_WKT` column:

```powershell
python -m analytics.prepare_input 'data/private/plans_raw.csv' 'data/private/plans_ready.csv' --crs EPSG:28992
python -m pipeline.quality --config config.yaml --plans 'data/private/plans_ready.csv'
```

The second command is for the **simplified** Part 1. Older `src/lmvw_pipeline/` repositories use their existing documented validation command and input configuration instead.

Alternatively, explicitly choose the supplied WGS84 column:

```powershell
python -m analytics.prepare_input 'data/private/plans_raw.csv' 'data/private/plans_wgs84.csv' --wkt-column Polygon_WKT_4326 --crs EPSG:4326
```

The helper copies the selected geometry into the name consumed by Part 1, preserves the previous Polygon_WKT as `Original_Polygon_WKT`, and writes an explicit CRS. It performs no coordinate transformation and no business-data correction. It refuses an existing output file or a conflicting CRS. Remaining invalid geometries still need DQ review. Literal Markdown/HTML header markers such as `**` or `&#...;` are rejected; export the CSV again from the source instead of silently removing formatting tokens.

### Real plans also need appropriate external sources

Adding CRS solves an input-metadata issue. It does **not** turn synthetic source fixtures into real BAG/BRK/DSO data. With `sources.mode: fixtures`, the DSO fixture only covers its sample geometry hashes. Real plan contours can therefore produce `Synthetic DSO fixture does not cover this search geometry` after validation starts passing.

Use the standalone validation command first. For actual enrichment, explicitly configure live sources and provide the correct DSO environment's key through Part 1's existing secret mechanism. Do not put the key in `config.yaml`, this reporting module, a notebook, a terminal command argument or Git. Do not disable quality rules or use `include_rejected_plans` to hide the CRS problem. Existing exposed keys still require rotation independently of this reporting addition.

## Synthetic demonstration and verification

The 36 plans cover three fictional municipalities. Six records have blocking problems, two records share an area key, one accepted plan has negative net capacity, and two records have incomplete numeric details. All source geometries and API-shaped responses are fictional. The source fixtures are built by code and passed through the **unchanged engineering pipeline**; the report numbers are not separately fabricated dashboard constants.

Observed example results:

| Measurement | Result |
| --- | ---: |
| Input / accepted / rejected records | 36 / 30 / 6 |
| Accepted gross / demolition / net capacity | 1,590 / 97 / 1,493 |
| Plan-validation findings / link warnings | 11 / 14 |
| Plan-source relationships | 318 |
| CSV tables in the example export | 17 |

Rebuild (optional, simplified Part 1 required):

```powershell
python -m analytics.make_demo --replace
python -m analytics.report --output analytics/output/rebuilt_demo.html
```

Tests:

```powershell
python -m pip install pytest
python -m pytest analytics/tests -q
```

At build time, **29 analytics tests passed**. Combined with the unchanged simplified pipeline, **47 tests passed**. The three optional Streamlit smoke tests were skipped because Streamlit could not be installed in this network-restricted build environment. App syntax was checked, but this is **not** a claim of a running Streamlit server or an executed UI test. Running the tests after installing `analytics/requirements.txt` executes those additional smoke tests.

The actual standalone HTML was rendered in Chromium with networking disabled: 11 plots/maps rendered, no JavaScript errors or external requests occurred, and toggling a source-map legend changed its layer visibility. The rendered layout was visually reviewed. Both supplied pipeline versions' eight-plan example exports were also read successfully. No original repository file was changed. Real API calls, Windows execution, deployment and the user's full 153-row input were not tested during this addition.

Test environment for the executed numerical/reporting code: Python 3.13.5, Pandas 2.2.3, Plotly 6.5.2, Shapely 2.1.2. The broad compatible requirements are not a fully resolved dependency lockfile.

## Portfolio interpretation

Read the finished report first, then `data.py` for the analytical population and metric definitions, and `charts.py` for visualisation. The report demonstrates the connection between engineering decisions and what a stakeholder sees. This is a post-demo reconstruction outside INKIS, not evidence that these Python interface files were part of the original tender. Attribute only the original integrations, queries and visual designs you actually contributed.

No predictive model, CBS realised-housing dataset, public confidentiality projection or production authorisation service is claimed. Root `NOTICE.md` and any relevant reuse restrictions remain applicable.

## Technical references

- Streamlit chart rendering: https://docs.streamlit.io/develop/api-reference/charts/st.plotly_chart
- Streamlit app testing: https://docs.streamlit.io/develop/api-reference/app-testing
- Self-contained Plotly HTML export: https://plotly.com/python/interactive-html-export/
- Official EPSG registry for the Dutch RD coordinate system: https://epsg.org/crs_28992/index.html
