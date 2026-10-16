# LMVW - from source data to an analytical report

This portfolio has two parts. The boundary between them is a **database-ready CSV export**, not an INKIS application or an SQL Server connection.

| Part | Purpose | Start reading |
| --- | --- | --- |
| **1. Data engineering** | Plan ingestion, Python quality rules, BAG/BRK/DSO extraction, geospatial relationships, relational exports | Existing project README, then `pipeline/run.py` in the simplified version |
| **2. Data analytics** | Analytical populations, capacity indicators, phasing, interactive polygon maps, quality interpretation and reporting | [Analytics README](analytics/README.md), then `analytics/data.py` and `analytics/report.py` |

```text
Raw housing plans + public source APIs
                 |
          PART 1 / ENGINEERING
     validate -> enrich -> spatial joins
                 |
          database_ready/*.csv
                 |
           PART 2 / ANALYTICS
    metrics -> maps -> findings -> report
```

![Synthetic report preview](analytics/demo/preview.png)

The [example HTML report](analytics/demo/report.html) can be downloaded and opened in a browser. GitHub's file preview does not execute it. The charts and vector maps need no network connection after the file is opened.

The optional local app provides municipality filters and plan selection:

```powershell
python -m pip install -r analytics/requirements.txt
python -m streamlit run analytics/app.py --server.address 127.0.0.1 --browser.gatherUsageStats false
```

The addition does not rename, move or overwrite Part 1. Earlier repositories with `src/lmvw_pipeline/` can use the same analytics reader: both supplied pipeline versions export the same fields used here.

## What this demonstrates

The analytical work is not just chart styling. It defines which records can be used, avoids many-to-many double counting, distinguishes planned capacity from realised dwellings, preserves unknown values and five-year buckets, and makes spatial evidence inspectable.

This is a portfolio reconstruction of a tender demonstration originally using INKIS/IO Factory. The new Python report was built after that demonstration. It should not be described as the software used in the original tender, nor as a production or legally authoritative system. Personal attribution should cover only the source integrations, analysis, queries and visual designs actually contributed by the portfolio author; team contributions remain team contributions.

Only synthetic data is included. Local real-data reports are not public exports, even when their source APIs are public. Existing ownership and reuse notices continue to apply.
