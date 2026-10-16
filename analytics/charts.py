"""Small Plotly charts shared by the browser report and Streamlit app.

Maps are metric vector maps in RD New, not street maps. They require no map
provider, network, tile requests, tokens or geographical inference. Polygon
interior rings are drawn too; no false fill is painted over holes.
"""
from __future__ import annotations

from html import escape
import math

import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
from shapely import from_wkt

from .data import (Bundle, capacity_by, phasing, breakdown, eligible, issue_rules,
                   source_metrics, source_objects, dso_evidence, RELATIONS)


def finish(fig: go.Figure, title: str, height: int = 370) -> go.Figure:
    fig.update_layout(title=dict(text=title, x=0), template="plotly_white", height=height,
                      margin=dict(l=15, r=15, t=55, b=45),
                      font=dict(family="Arial, sans-serif", size=13),
                      legend=dict(orientation="h", y=-0.23), hovermode="closest")
    return fig


def empty_chart(title: str, text: str = "Geen bruikbare gegevens in deze selectie") -> go.Figure:
    fig = go.Figure()
    fig.add_annotation(text=text, x=0.5, y=0.5, xref="paper", yref="paper", showarrow=False)
    fig.update_xaxes(visible=False)
    fig.update_yaxes(visible=False)
    return finish(fig, title)


def dashboard_charts(bundle: Bundle, plans: pd.DataFrame) -> list[tuple[str, go.Figure, str]]:
    items = []
    by_city = capacity_by(plans, "municipality")
    fig = (px.bar(by_city, x="municipality", y="gross", labels={"municipality": "Gemeente", "gross": "Bruto woningen"})
           if not by_city.empty else empty_chart("Bruto plancapaciteit per gemeente"))
    items.append(("gemeente", finish(fig, "Bruto plancapaciteit per gemeente"),
                  "Alleen toegelaten planrecords. Geen optelling na een many-to-many bronjoin."))
    hard = capacity_by(plans, "hard_soft")
    fig = (px.bar(hard, x="hard_soft", y="gross", labels={"hard_soft": "Planstatus", "gross": "Bruto woningen"})
           if not hard.empty else empty_chart("Hard versus zacht"))
    items.append(("status", finish(fig, "Hard versus zacht"), "HARD en SOFT volgen de classificatie uit deel 1; geen kansmodel."))
    phases = phasing(bundle, plans)
    fig = (px.bar(phases, x="period_label", y="homes", hover_data=["missing"],
                  labels={"period_label": "Periode", "homes": "Geplande woningen", "missing": "Ontbrekende aantallen"})
           if not phases.empty else empty_chart("Geplande oplevering"))
    fig.update_xaxes(type="category")
    items.append(("fasering", finish(fig, "Geplande oplevering per periode"),
                  "2036 t/m 2040 en 2041 t/m 2045 blijven vijfjaarstotalen; ze zijn niet over jaren verdeeld."))
    housing = breakdown(bundle, plans, "housing_type")
    fig = (px.bar(housing, x="homes", y="source_field", orientation="h", hover_data=["missing"],
                  labels={"source_field": "Woningtype", "homes": "Geplande woningen", "missing": "Ontbrekend"})
           if not housing.empty else empty_chart("Woningprogramma"))
    items.append(("woningtype", finish(fig, "Woningprogramma"),
                  "Bekende aantallen per woningtype. Een lege bronwaarde is niet hetzelfde als de categorie onbekend."))
    tenure = breakdown(bundle, plans, "tenure_price")
    fig = (px.bar(tenure, x="homes", y="source_field", orientation="h", hover_data=["missing"],
                  labels={"source_field": "Categorie", "homes": "Geplande woningen", "missing": "Ontbrekend"})
           if not tenure.empty else empty_chart("Eigendom en prijssegment"))
    items.append(("prijssegment", finish(fig, "Eigendom en prijssegment", 600),
                  "Categorieen zoals aangeleverd. Geen herberekening op basis van actuele prijsgrenzen."))
    return items


def quality_charts(bundle: Bundle, plans: pd.DataFrame) -> list[tuple[str, go.Figure, str]]:
    states = plans["processing_status"].value_counts().rename_axis("status").reset_index(name="records")
    fig = (px.bar(states, x="status", y="records", labels={"status": "Verwerkingsstatus", "records": "Planrecords"})
           if not states.empty else empty_chart("Datakwaliteit"))
    rules = issue_rules(bundle, plans)
    rule_fig = (px.bar(rules, x="rule_id", y="findings", color="severity", hover_data=["records"],
                       labels={"rule_id": "Regel", "findings": "Bevindingen", "severity": "Ernst", "records": "Records"})
                if not rules.empty else empty_chart("Bevindingen per regel", "Geen bevindingen voor deze selectie"))
    metrics = source_metrics(bundle, plans)
    measurable = metrics[metrics["coverage_pct"].notna()]
    cover = (px.bar(measurable, x="source", y="coverage_pct", labels={"source": "Bron", "coverage_pct": "% toegelaten records"})
             if not measurable.empty else empty_chart("Brondekking", "Bronnen niet bevraagd of geen toegelaten records"))
    cover.update_yaxes(range=[0, 100])
    evidence = dso_evidence(bundle, plans)
    dso = (px.bar(evidence, x="relation_status", y="relations", hover_data=["documents"],
                 labels={"relation_status": "Bewijsstatus", "relations": "Plan-documentrelaties", "documents": "Unieke documenten"})
           if not evidence.empty else empty_chart("DSO-bewijs", "Geen DSO-relaties voor deze selectie"))
    return [("dq_status", finish(fig, "Toegelaten, waarschuwing of afgekeurd"), "READY en WARNING zijn toegelaten; REJECTED niet."),
            ("dq_regels", finish(rule_fig, "Bevindingen per regel"), "Bevindingen en records zijn verschillende telgrootheden."),
            ("brondekking", finish(cover, "Records met ten minste een bronrelatie"),
             "DSO-dekking bevat ook kandidaten. Dekking is geen maat voor inhoudelijke juistheid of bouwrealisatie."),
            ("dso_bewijs", finish(dso, "DSO: kandidaat versus ruimtelijk bewijs"),
             "Ruimtelijke overlap is geen inhoudelijke bevestiging. De kolom substantively_confirmed blijft apart.")]


def _segments(geom):
    if geom.geom_type == "Point":
        yield list(geom.coords)
    elif geom.geom_type == "Polygon":
        yield list(geom.exterior.coords)
        for ring in geom.interiors:
            yield list(ring.coords)
    elif hasattr(geom, "geoms"):
        for part in geom.geoms:
            yield from _segments(part)


def _trace(frame: pd.DataFrame, name: str, label_column: str, *, width: int = 2,
           dash: str = "solid", points: bool = False) -> tuple[go.Scatter, int]:
    xs, ys, labels = [], [], []
    omitted = 0
    for _, row in frame.iterrows():
        wkt = row.get("geometry_wkt")
        crs = row.get("crs")
        if pd.isna(wkt) or pd.isna(crs) or crs != "EPSG:28992":
            omitted += 1
            continue
        try:
            geom = from_wkt(str(wkt))
            if geom.is_empty or not geom.is_valid or not all(math.isfinite(v) for v in geom.bounds):
                raise ValueError()
        except Exception:
            omitted += 1
            continue
        label = escape(str(row.get(label_column, name)))
        for segment in _segments(geom):
            xs.extend(float(xy[0]) for xy in segment)
            ys.extend(float(xy[1]) for xy in segment)
            labels.extend([label] * len(segment))
            xs.append(None); ys.append(None); labels.append(None)
    trace = go.Scatter(x=xs, y=ys, text=labels, mode="markers" if points else "lines", name=name,
                       line=dict(width=width, dash=dash), marker=dict(size=7),
                       hovertemplate="%{text}<br>RD x: %{x:.1f} m<br>RD y: %{y:.1f} m<extra>%{fullData.name}</extra>")
    return trace, omitted


def vector_map(bundle: Bundle, plans: pd.DataFrame, selected_record: str | None = None) -> tuple[go.Figure, int]:
    """Outline map with separate source traces. Every ring/part stays intact.

    Plan overview: accepted plans only. Detail: selected record, including a
    rejected record if its geometry was valid. Objects come from export links,
    NOT from a new spatial query. Coordinates are never relabelled as WGS84.
    """
    fig = go.Figure()
    omitted = 0
    visible = eligible(plans) if selected_record is None else plans[plans["record_id"].eq(selected_record)]
    if selected_record is None:
        for state, group in visible.groupby("hard_soft", dropna=False):
            trace, count = _trace(group, f"Plannen {state}", "plan_name", width=3)
            fig.add_trace(trace); omitted += count
    else:
        trace, count = _trace(visible, "Plancontour", "plan_name", width=4)
        fig.add_trace(trace); omitted += count
        for label, (_, _, ids, _) in RELATIONS.items():
            objects = source_objects(bundle, visible, label)
            if label == "DSO documenten":
                for status, group in objects.groupby("relation_status"):
                    trace, count = _trace(group, f"DSO: {status}", "title", dash="dash")
                    fig.add_trace(trace); omitted += count
            else:
                trace, count = _trace(objects, label, ids[-1], points=label == "BAG verblijfsobjecten",
                                       dash="dot" if label == "BRK percelen" else "solid")
                fig.add_trace(trace); omitted += count
    if not any(any(v is not None for v in trace.x) for trace in fig.data):
        return empty_chart("Vectorplankaart", "Geen geldige geometrie in deze selectie"), omitted
    finish(fig, "Plan en bronobjecten" if selected_record else "Ligging van toegelaten woningbouwplannen", 580)
    fig.update_xaxes(title="RD x (meter)", tickformat=".0f", constrain="domain")
    fig.update_yaxes(title="RD y (meter)", tickformat=".0f", scaleanchor="x", scaleratio=1)
    fig.update_layout(dragmode="pan", legend=dict(orientation="h", y=-0.17), uirevision=selected_record or "overview")
    if selected_record and not visible.empty:
        # A municipality-wide DSO document must not make the selected plan tiny.
        # Offer an explicit switch between local plan context and all source extents.
        row = visible.iloc[0]
        if pd.notna(row.get("geometry_wkt")) and row.get("crs") == "EPSG:28992":
            try:
                geom = from_wkt(str(row["geometry_wkt"]))
                if not geom.is_valid or geom.is_empty:
                    raise ValueError()
                x1, y1, x2, y2 = geom.bounds
                padding = max(x2-x1, y2-y1) * 0.5 + 20
                xr, yr = [x1-padding, x2+padding], [y1-padding, y2+padding]
                fig.update_xaxes(range=xr, autorange=False)
                fig.update_yaxes(range=yr, autorange=False)
                fig.update_layout(margin=dict(t=90), updatemenus=[dict(type="buttons", direction="right",
                    x=1, xanchor="right", y=1.16, yanchor="top", buttons=[
                        dict(label="Zoom op plan", method="relayout", args=[{"xaxis.range": xr, "yaxis.range": yr,
                                "xaxis.autorange": False, "yaxis.autorange": False}]),
                        dict(label="Alle bronobjecten", method="relayout", args=[{"xaxis.autorange": True, "yaxis.autorange": True}])])])
            except Exception:
                pass  # The missing/invalid geometry was already counted above.
    return fig, omitted
