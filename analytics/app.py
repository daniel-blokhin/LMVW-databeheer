"""Local report app. Start from the repository root:

python -m streamlit run analytics/app.py --server.address 127.0.0.1 --browser.gatherUsageStats false

Set LMVW_BUNDLE_DIR to analyse your own database_ready directory. This is NOT a
public multi-user application: there is no authentication or publication filter.
"""
from __future__ import annotations

import os
from pathlib import Path
import sys

# Streamlit also runs this file directly. Import this repository's analytics package.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pandas as pd
import streamlit as st

from analytics.data import (DEMO, DataError, eligible, filter_plans, findings, issue_rules,
                            kpis, load_bundle, number, scoped_issues, source_metrics,
                            source_objects, RELATIONS)
from analytics.charts import dashboard_charts, quality_charts, vector_map
from analytics.report import make_html

st.set_page_config(page_title="LMVW | Analytics", layout="wide")
st.markdown("""<style>
.block-container{max-width:1400px;padding-top:2rem}h1{letter-spacing:-1px}
[data-testid="stMetric"]{border:1px solid #dce4e9;border-top:3px solid #16687b;border-radius:6px;padding:16px}
</style>""", unsafe_allow_html=True)  # Constant CSS only, never raw source text.

st.sidebar.title("LMVW / Analytics")
st.sidebar.caption("Deel 2 - onafhankelijke portfolio-reconstructie")
local = os.environ.get("LMVW_BUNDLE_DIR")
options = {"Synthetische demo (36 plannen)": DEMO}
if local:
    options["Eigen lokale export"] = Path(local)
choice = st.sidebar.selectbox("Dataset", list(options), index=1 if local else 0)
path = options[choice]
try:
    # Do not put private records into a cross-session cache.
    bundle = load_bundle(path)
except (DataError, OSError) as exc:
    st.error(str(exc))
    st.info("Gebruik de database_ready-map van deel 1, niet een ruwe plans.csv. Controleer ook manifest.json.")
    st.stop()

st.sidebar.caption("Bron: " + str(bundle.path))
if choice == "Eigen lokale export":
    st.sidebar.warning("Alleen lokaal en bevoegd gebruiken. Dit is geen publiek dashboard en geen autorisatiemechanisme.")
    if not st.sidebar.checkbox("Ik ben bevoegd om deze gegevens lokaal te analyseren."):
        st.info("Bevestig lokaal gebruik van je eigen export in de zijbalk.")
        st.stop()
else:
    st.sidebar.info("Alle namen, aantallen, geometrie en bronobjecten in deze demo zijn fictief.")

cities = sorted(bundle["plans"]["municipality"].fillna("(ontbreekt)").unique())
selected_cities = st.sidebar.multiselect("Gemeente", cities, default=cities)
states = ["HARD", "SOFT", "UNKNOWN"]
selected_states = st.sidebar.multiselect("Planclassificatie", states, default=states)
plans = filter_plans(bundle, selected_cities, selected_states)
page = st.sidebar.radio("Rapportonderdeel", ["Portefeuille", "Kaarten en plan", "Datakwaliteit"])
st.sidebar.caption("Geen selectie betekent geen records. Capaciteits-KPI's sluiten afgekeurde records altijd uit.")
st.sidebar.caption("Draai deel 1 opnieuw voor nieuwe brondata. Deze app doet zelf geen API-aanroepen.")

st.caption("LMVW  /  DEEL 2  /  DATA ANALYTICS REPORT")
st.title({"Portefeuille": "Van woningbouwdata naar inzicht", "Kaarten en plan": "Van plancontour naar bronobject",
          "Datakwaliteit": "Hoe betrouwbaar is deze selectie?"}[page])
st.caption(bundle.classification + " | Bronmodus: " + bundle.mode + " | Run: " + bundle.run_id)
metrics = kpis(plans)
if metrics["input"] and not metrics["accepted"]:
    st.warning("Alle geselecteerde records zijn afgekeurd. Capaciteit is niet beschikbaar; lege bronresultaten betekenen niet nul woningen.")
    rules = issue_rules(bundle, plans)
    if rules["rule_id"].eq("DQ-GEO-001").any():
        st.info("DQ-GEO-001 gevonden: controleer Polygon_WKT en een expliciete CRS, of de ingestelde GeoPackage-koppeling.")


def show_chart(item):
    key, figure, caption = item
    st.plotly_chart(figure, use_container_width=True, key=key, config={"displaylogo": False})
    st.caption(caption)


if page == "Portefeuille":
    columns = st.columns(4)
    for col, label, value in zip(columns, ["Toegelaten planrecords", "Bruto plancapaciteit", "Netto toevoegingen", "Afgekeurde records"],
                                  [metrics["accepted"], metrics["gross"], metrics["net"], metrics["rejected"]]):
        col.metric(label, number(value))
    st.caption(f"Populatie: {metrics['input']} aangeleverde planrecords. Alleen READY en WARNING tellen mee in capaciteit.")
    with st.expander("Wat valt op?", expanded=True):
        for note in findings(bundle, plans):
            st.write(note)
    charts = dashboard_charts(bundle, plans)
    for index in range(0, 4, 2):
        left, right = st.columns(2)
        with left: show_chart(charts[index])
        with right: show_chart(charts[index + 1])
    show_chart(charts[4])
    with st.expander("Controleer de onderliggende planrecords"):
        st.dataframe(plans[["plan_name", "municipality", "hard_soft", "gross_capacity", "demolition",
                            "net_capacity_calculated", "processing_status", "confidential"]],
                     use_container_width=True, hide_index=True)
    if st.button("Maak HTML-rapport van deze selectie"):
        content = make_html(bundle, plans)
        st.download_button("Rapport opslaan", content, file_name="lmvw-analytics.html", mime="text/html")
        st.caption("Het HTML-bestand bevat deze selectie. Een export van echte plandata blijft intern.")

elif page == "Kaarten en plan":
    kind = st.radio("Kaartniveau", ["Overzicht", "Plandetail"], horizontal=True)
    selected_id = None
    selected = None
    if kind == "Plandetail" and not plans.empty:
        labels = {row.record_id: f"{row.municipality} | {row.plan_name} | rij {int(row.source_row_number)}"
                  for row in plans.itertuples()}
        selected_id = st.selectbox("Planrecord (niet alleen Koppelcode)", list(labels), format_func=labels.get)
        selected = plans[plans["record_id"].eq(selected_id)]
        if selected.iloc[0]["processing_status"] == "REJECTED":
            st.warning("Dit record is afgekeurd en is niet verrijkt. Een eventueel geldige plancontour mag wel zichtbaar zijn.")
    figure, omitted = vector_map(bundle, plans, selected_id)
    st.plotly_chart(figure, use_container_width=True, config={"displaylogo": False, "scrollZoom": True})
    st.caption(f"RD New, meters, gelijke schaal. Geen achtergrondkaart of externe kaartdienst. "
               f"Klik op de legenda om lagen te verbergen. Niet getekende geometrieen: {omitted}.")
    if selected is not None:
        st.subheader("Herleidbare bronrelaties")
        for label in RELATIONS:
            frame = source_objects(bundle, selected, label)
            with st.expander(f"{label}: {len(frame)} relaties", expanded=label == "DSO documenten"):
                st.dataframe(frame.drop(columns=["geometry_wkt", "crs", "run_id", "record_id"], errors="ignore"),
                             use_container_width=True, hide_index=True)
        st.info("BAG-objecten tonen wat ruimtelijk is gekoppeld, niet automatisch nieuw gerealiseerde woningen. "
                "DSO-kandidaten, ruimtelijk bewijs en inhoudelijke bevestiging zijn afzonderlijke begrippen.")
else:
    issues = scoped_issues(bundle, plans)
    a, b, c, d = st.columns(4)
    a.metric("Records in selectie", len(plans))
    b.metric("Records met bevindingen", issues["record_id"].nunique())
    c.metric("Foutbevindingen", int(issues["severity"].eq("ERROR").sum()))
    d.metric("Waarschuwingen", int(issues["severity"].eq("WARNING").sum()))
    charts = quality_charts(bundle, plans)
    for index in range(0, 4, 2):
        left, right = st.columns(2)
        with left: show_chart(charts[index])
        with right: show_chart(charts[index + 1])
    st.subheader("Welke regel blokkeert de verwerking?")
    st.dataframe(issue_rules(bundle, plans), use_container_width=True, hide_index=True)
    with st.expander("Bevindingen per planrecord"):
        st.dataframe(issues.drop(columns=["run_id", "record_id", "issue_id"], errors="ignore"),
                     use_container_width=True, hide_index=True)
    with st.expander("Bronstatus en tellingen"):
        st.dataframe(source_metrics(bundle, plans), use_container_width=True, hide_index=True)
    unassigned = bundle["dq_issues"][bundle["dq_issues"]["record_id"].isna()]
    if not unassigned.empty:
        st.warning(f"Deze run bevat daarnaast {len(unassigned)} bevindingen zonder planrecord. Ze vallen buiten gemeentefilters.")
        st.dataframe(unassigned, use_container_width=True, hide_index=True)

st.divider()
st.caption("Portfolio-reconstructie buiten INKIS. Geen productieapplicatie, voorspelling, publieke toegang of juridische duiding.")
