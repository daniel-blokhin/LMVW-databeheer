"""Interactive geographic maps for the local LMVW analytics reconstruction.

Uses the EXISTING database_ready tables and plan/source relations. No external
API calls, new spatial matches or data engineering modifications are made here.
Coordinates must have an explicit supported CRS; polygons are reprojected from
RD New to WGS84 before being drawn over a web tile basemap.

SECURITY: This module is for authorised local use. It does NOT implement access
control and MUST NOT be used to publish confidential plan geometries.
"""
from __future__ import annotations

import math
from html import escape
from typing import Any

import pandas as pd
import plotly.graph_objects as go
from pyproj import Transformer
from shapely import from_wkt
from shapely.geometry import mapping
from shapely.ops import transform

from .data import Bundle, RELATIONS, eligible, source_objects
from .charts import empty_chart

# No API keys required. Tiles are requested from third parties by the *browser*.
# "white-bg" is an offline-friendly fallback (no map tiles / no street names).
MAP_STYLES = {
    "Lichte stratenkaart (CARTO)": "carto-positron",
    "OpenStreetMap": "open-street-map",
    "Zonder achtergrondtegels (offline)": "white-bg",
}
DEFAULT_STYLE = "carto-positron"

STATE_COLORS = {
    "HARD": "#4964e8",
    "SOFT": "#f2754f",
    "UNKNOWN": "#8a96a4",
}
LAYER_STYLE = {
    "DSO documenten": ("#e2a537", 1.2, 0.10),
    "BRK percelen": ("#9066cf", 1.5, 0.16),
    "BAG panden": ("#e05445", 2.0, 0.31),
    "BAG verblijfsobjecten": ("#00a88b", 2.0, 0.85),
}

_TRANSFORMERS = {
    "EPSG:28992": Transformer.from_crs("EPSG:28992", "EPSG:4326", always_xy=True),
    "EPSG:4326": None,
}


def _geometry(row: pd.Series):
    """Return WGS84 Shapely geometry, rejecting missing/invalid CRS and shapes."""
    raw, crs = row.get("geometry_wkt"), row.get("crs")
    if pd.isna(raw) or not str(raw).strip() or pd.isna(crs):
        raise ValueError("missing WKT or CRS")
    crs = str(crs).strip().upper()
    if crs not in _TRANSFORMERS:
        raise ValueError("unsupported or ambiguous CRS")
    geom = from_wkt(str(raw))
    if geom.is_empty or not geom.is_valid:
        raise ValueError("invalid geometry")
    if any(not math.isfinite(v) for v in geom.bounds):
        raise ValueError("non-finite geometry")
    transformer = _TRANSFORMERS[crs]
    if transformer:
        geom = transform(transformer.transform, geom)
    if geom.is_empty or not geom.is_valid or any(not math.isfinite(v) for v in geom.bounds):
        raise ValueError("invalid geometry after reprojecting")
    x1, y1, x2, y2 = geom.bounds
    if x1 < -180 or x2 > 180 or y1 < -85 or y2 > 85:
        raise ValueError("coordinates outside the supported web-map bounds")
    return geom


def _safe(value: Any) -> str:
    """Escape untrusted names (including accidental Plotly %{...} placeholders)."""
    if value is None or value is pd.NA:
        return "onbekend"
    try:
        if pd.isna(value):
            return "onbekend"
    except (TypeError, ValueError):
        pass
    return escape(str(value).replace("%{", "%&#123;"), quote=True)


def _items(frame: pd.DataFrame, label_column: str) -> tuple[list[dict], list[dict], int]:
    polygons, points, skipped = [], [], 0
    for i, (_, row) in enumerate(frame.iterrows()):
        try:
            geom = _geometry(row)
        except (ValueError, TypeError, AttributeError):
            skipped += 1
            continue
        label = _safe(row.get(label_column))
        # No names or other attributes are copied into the GeoJSON payload.
        # Hover values live exclusively in the associated Plotly trace.
        if geom.geom_type in {"Polygon", "MultiPolygon"}:
            polygons.append({"id": str(i), "geometry": mapping(geom), "label": label, "bounds": geom.bounds})
        elif geom.geom_type == "Point":
            points.append({"lat": float(geom.y), "lon": float(geom.x), "label": label, "bounds": geom.bounds})
        elif geom.geom_type == "MultiPoint":
            for item in geom.geoms:
                points.append({"lat": float(item.y), "lon": float(item.x), "label": label, "bounds": geom.bounds})
        else:
            skipped += 1  # Unsupported geometry type; do not silently turn a line into a polygon.
    return polygons, points, skipped


def _polygon_trace(name: str, items: list[dict], color: str, *, line_width: float,
                   opacity: float) -> go.Choroplethmap | None:
    if not items:
        return None
    geojson = {"type": "FeatureCollection", "features": [
        {"type": "Feature", "id": item["id"], "properties": {}, "geometry": item["geometry"]}
        for item in items
    ]}
    return go.Choroplethmap(
        name=name, geojson=geojson, featureidkey="id",
        locations=[item["id"] for item in items],
        z=[1] * len(items), colorscale=[[0, color], [1, color]],
        zmin=0, zmax=1, showscale=False,
        marker=dict(line=dict(color=color, width=line_width), opacity=opacity),
        text=[item["label"] for item in items],
        hovertemplate="%{text}<extra>%{fullData.name}</extra>",
        showlegend=True,
    )


def _points_trace(name: str, items: list[dict], color: str) -> go.Scattermap | None:
    if not items:
        return None
    return go.Scattermap(
        name=name, lat=[p["lat"] for p in items], lon=[p["lon"] for p in items],
        mode="markers", marker=dict(color=color, size=9),
        text=[p["label"] for p in items],
        hovertemplate="%{text}<extra>%{fullData.name}</extra>", showlegend=True,
    )


def _append(fig: go.Figure, name: str, frame: pd.DataFrame, label_col: str,
            color: str, line_width: float = 2, opacity: float = 0.4) -> tuple[int, list[tuple]]:
    polygons, points, skipped = _items(frame, label_col)
    poly = _polygon_trace(name, polygons, color, line_width=line_width, opacity=opacity)
    dots = _points_trace(name + " (punten)", points, color)
    if poly:
        fig.add_trace(poly)
    if dots:
        fig.add_trace(dots)
    return skipped, [p["bounds"] for p in polygons + points]


def _view(bounds: list[tuple], selected: bool) -> tuple[dict, float]:
    if not bounds:
        return {"lon": 5.3, "lat": 52.1}, 7
    left = min(b[0] for b in bounds)
    bottom = min(b[1] for b in bounds)
    right = max(b[2] for b in bounds)
    top = max(b[3] for b in bounds)
    lon, lat = (left + right) / 2, (bottom + top) / 2
    # Approximate fit for the 950 x 620 map area; intentionally leave padding.
    lon_range = max((right - left) * 1.55, 0.00012)
    lat_range = max((top - bottom) * 1.55, 0.00008)
    cosine = max(math.cos(math.radians(lat)), 0.2)
    zoom_lon = math.log2(360 * 900 / (512 * lon_range))
    zoom_lat = math.log2(360 * 520 * cosine / (512 * lat_range))
    zoom = max(2.0, min(18.0 if selected else 15.0, zoom_lon, zoom_lat))
    return {"lon": lon, "lat": lat}, zoom


def geo_map(bundle: Bundle, plans: pd.DataFrame, selected_record: str | None = None,
            *, map_style: str = DEFAULT_STYLE) -> tuple[go.Figure, int]:
    """Real tile-map overview/detail; returns (Plotly Figure, skipped geometry count).

    Only accepted plans appear in overview. A selected rejected plan can still be
    inspected but has no enrichment, mirroring the existing RD technical map.
    Data is limited by the caller's selected plan rows, never Koppelcode alone.
    This is NOT a publication authorisation or confidentiality filter.
    """
    if map_style not in MAP_STYLES.values():
        raise ValueError("Ongeldige kaartstijl")
    visible = (eligible(plans) if selected_record is None else
               plans[plans["record_id"].eq(selected_record)].copy())
    if visible.empty:
        return empty_chart("Kaart", "Geen geldige geometrie in deze selectie"), 0

    fig = go.Figure()
    skipped = 0
    plan_bounds: list[tuple] = []
    if selected_record is not None:
        # Large DSO documents must not determine initial camera bounds. Display
        # wide DSO polygons but zoom on the selected plan polygon.
        for label in ("DSO documenten", "BRK percelen", "BAG panden", "BAG verblijfsobjecten"):
            frame = source_objects(bundle, visible, label)
            color, width, opacity = LAYER_STYLE[label]
            if label == "DSO documenten" and not frame.empty:
                # Preserve provenance: spatial match != legal/substantive match.
                for status, group in frame.groupby("relation_status", dropna=False, sort=True):
                    n, _ = _append(fig, f"DSO: {status}", group, "title", color, width, opacity)
                    skipped += n
            else:
                n, _ = _append(fig, label, frame, RELATIONS[label][2][-1], color, width, opacity)
                skipped += n
        n, plan_bounds = _append(fig, "Plancontour", visible, "plan_name", "#285ee8", 3.5, 0.28)
        skipped += n
    else:
        for state in ("HARD", "SOFT", "UNKNOWN"):
            group = visible[visible["hard_soft"].fillna("UNKNOWN").eq(state)]
            if group.empty:
                continue
            n, b = _append(fig, f"Plannen {state}", group, "plan_name", STATE_COLORS[state], 2.3, 0.4)
            skipped += n
            plan_bounds.extend(b)
    if not fig.data:
        return empty_chart("Kaart", "Geen geldige geometrie in deze selectie"), skipped

    center, zoom = _view(plan_bounds, selected=selected_record is not None)
    title = "Plan en bronobjecten" if selected_record else "Ligging van toegelaten woningbouwplannen"
    fig.update_layout(
        title=dict(text=title, x=0), height=620,
        map=dict(style=map_style, center=center, zoom=zoom),
        margin=dict(l=8, r=8, t=74, b=70),
        updatemenus=[dict(type="dropdown", direction="down", x=1, xanchor="right",
                          y=1.075, yanchor="bottom", showactive=True,
                          buttons=[dict(label=label, method="relayout",
                                        args=[{"map.style": style}])
                                   for label, style in MAP_STYLES.items()])],
        legend=dict(orientation="h", y=-0.08, x=0),
        font=dict(family="Arial, sans-serif", size=12),
        uirevision=f"geo:{selected_record or 'overview'}:{map_style}",
    )
    return fig, skipped
