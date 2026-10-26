"""Generate a self-contained HTML analytics report. No web server required.

python -m analytics.report --output data/reports/report.html
python -m analytics.report --bundle data/runs/<run>/database_ready --output data/reports/private.html
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
from html import escape
from pathlib import Path

import pandas as pd
import plotly.io as pio
from plotly.offline import get_plotlyjs

from .data import (Bundle, DEMO, DataError, eligible, filter_plans, findings, issue_rules,
                   kpis, load_bundle, number, source_metrics, source_objects, RELATIONS)
from .charts import dashboard_charts, quality_charts, vector_map

CSS = """
:root{--ink:#152838;--muted:#5e6e7b;--line:#dce4e9;--paper:#f3f6f8;--accent:#16687b}
*{box-sizing:border-box}html{scroll-behavior:smooth}body{margin:0;background:var(--paper);color:var(--ink);font:15px/1.6 'Segoe UI',Arial,sans-serif}
.hero{background:#102f42;color:#fff;padding:44px max(5%,calc((100% - 1240px)/2));padding-bottom:34px}.eyebrow{font-size:12px;text-transform:uppercase;letter-spacing:2px;color:#a2d6df}
h1{font-size:40px;font-weight:650;letter-spacing:-1.3px;line-height:1.15;margin:14px 0}h2{font-size:27px;margin:0 0 8px}h3{margin:0;font-size:17px}.hero p{max-width:800px;color:#d2dfe7;margin:14px 0}
.chip{display:inline-block;background:#20485a;border:1px solid #507180;color:#e4f2f6;border-radius:4px;padding:5px 10px;font-size:11px;letter-spacing:.5px;margin:4px 6px 0 0}
nav{position:sticky;top:0;z-index:100;background:white;border-bottom:1px solid var(--line);padding:14px max(5%,calc((100% - 1240px)/2));display:flex;gap:30px}nav a{color:var(--ink);font-weight:600;text-decoration:none;font-size:13px}
main{max-width:1280px;margin:auto;padding:30px 20px 60px}section{scroll-margin-top:75px;margin-bottom:42px}.section-title{display:flex;gap:16px;align-items:baseline;margin-bottom:16px}.index{font-size:12px;color:var(--accent);font-weight:700;letter-spacing:2px}
.intro{max-width:990px;color:var(--muted);margin:0 0 20px}.cards{display:grid;grid-template-columns:repeat(4,1fr);gap:14px;margin-bottom:22px}.card{background:white;border:1px solid var(--line);border-top:3px solid var(--accent);border-radius:6px;padding:19px}.label{font-size:12px;text-transform:uppercase;color:var(--muted);letter-spacing:.8px}.value{font-size:35px;font-weight:650;line-height:1.3;margin:7px 0}.small{font-size:12px;color:var(--muted)}
.grid{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:18px}.panel{min-width:0;background:white;border:1px solid var(--line);border-radius:6px;padding:18px;overflow:hidden}.panel.wide{grid-column:1/-1}.caption{color:var(--muted);font-size:12px;margin:8px 0 0}.findings{padding:22px 26px;background:#e8f2f4;border-left:4px solid var(--accent);margin:0 0 24px}.findings p{margin:8px 0}
.table-wrap{max-height:450px;overflow:auto;margin-top:14px;border:1px solid var(--line)}table{border-collapse:collapse;width:100%;font-size:12px;background:white}th,td{padding:9px 12px;text-align:left;border-bottom:1px solid var(--line);vertical-align:top}th{background:#ecf2f5;position:sticky;top:0}footer{font-size:12px;color:var(--muted);border-top:1px solid var(--line);padding-top:18px}code{word-break:break-all;font-size:12px}details{margin:16px 0}summary{cursor:pointer;font-weight:600}a{color:var(--accent)}
@media(max-width:850px){.grid{grid-template-columns:1fr}.cards{grid-template-columns:repeat(2,1fr)}h1{font-size:30px}nav{gap:14px}.hero{padding:30px 22px}}
@media print{nav{position:static}.hero{background:white;color:#102f42}.hero p{color:#456}body{background:white}.panel{break-inside:avoid}.grid{display:block}.cards{display:flex}.table-wrap{max-height:none}}
"""


def _table(frame: pd.DataFrame) -> str:
    if frame.empty:
        return '<p class="small">Geen records in deze selectie.</p>'
    return '<div class="table-wrap">' + frame.to_html(index=False, escape=True, na_rep="n.v.t.", border=0) + '</div>'


def make_html(bundle: Bundle, plans: pd.DataFrame, *, selected_record: str | None = None) -> str:
    metrics = kpis(plans)
    accepted = eligible(plans)
    if selected_record is None and not accepted.empty:
        selected_record = str(accepted.sort_values("source_row_number").iloc[0]["record_id"])
    if selected_record is not None and not plans["record_id"].eq(selected_record).any():
        raise DataError("Het geselecteerde planrecord valt buiten de rapportselectie.")
    notes = findings(bundle, plans)
    snapshot = str(bundle["pipeline_run"].iloc[0]["snapshot_utc"])
    created = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    city_scope = ", ".join(sorted(plans["municipality"].dropna().unique())) or "Lege selectie"
    blocks = []
    for key, title, value, label in [
        ("plans", "Toegelaten planrecords", metrics["accepted"], f"Van {metrics['input']} aangeleverde records"),
        ("gross", "Bruto plancapaciteit", metrics["gross"], "Gepland, niet gerealiseerd"),
        ("net", "Netto toevoegingen", metrics["net"], "Bruto minus sloop/onttrekkingen"),
        ("rejected", "Afgekeurde records", metrics["rejected"], "Uit capaciteitsanalyse uitgesloten"),
    ]:
        blocks.append(f'<div class="card" id="kpi-{key}"><div class="label">{title}</div>'
                      f'<div class="value">{number(value)}</div><div class="small">{label}</div></div>')

    def panel(key, figure, caption, wide=False):
        figure.update_layout(autosize=True)
        graph = pio.to_html(figure, full_html=False, include_plotlyjs=False, include_mathjax=False,
                            div_id="chart-" + key, config={"displaylogo": False, "responsive": True, "scrollZoom": False})
        return f'<article class="panel{" wide" if wide else ""}">{graph}<p class="caption">{escape(caption)}</p></article>'

    overview = "".join(panel(key, fig, caption, key == "prijssegment") for key, fig, caption in dashboard_charts(bundle, plans))
    overall_map, omitted = vector_map(bundle, plans)
    maps = panel("map-overview", overall_map,
                 f"RD New (EPSG:28992), metercoordinaten; geen stratenachtergrond. Zoom, versleep en schakel lagen via de legenda. "
                 f"Niet getekend wegens ontbrekende/ongeldige geometrie: {omitted}.", True)
    detail_tables = ""
    if selected_record:
        selected = plans[plans["record_id"].eq(selected_record)]
        name = str(selected.iloc[0]["plan_name"])
        detail, omitted = vector_map(bundle, plans, selected_record)
        maps += panel("map-detail", detail,
                      f"Geselecteerd record: {name}. Deze detailselectie ligt vast in dit HTML-rapport. "
                      f"De app laat andere records kiezen. {omitted} bronobjecten zonder tekenbare geometrie. "
                      "Lagen tonen gekoppelde bronobjecten; dit zijn geen bewezen gerealiseerde woningen.", True)
        for label in RELATIONS:
            frame = source_objects(bundle, selected, label).drop(columns=["geometry_wkt", "crs", "run_id", "record_id"], errors="ignore")
            detail_tables += f'<details><summary>{escape(label)}: {len(frame)} plan-bronrelaties</summary>{_table(frame)}</details>'
    quality = "".join(panel(key, fig, caption) for key, fig, caption in quality_charts(bundle, plans))
    source_table = _table(source_metrics(bundle, plans).round(2))
    rule_table = _table(issue_rules(bundle, plans))
    # Plotly embeds its JS locally once. There are no CDN scripts or map tiles.
    return f'''<!doctype html>
<html lang="nl"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>LMVW | Data Analytics Report</title><style>{CSS}</style><script>{get_plotlyjs()}</script></head>
<body><header class="hero"><div class="eyebrow">LMVW portfolio / Deel 2 / Data analytics</div>
<h1>Van woningbouwdata naar inzicht</h1><p>Capaciteit, ruimtelijke bronrelaties en datakwaliteit in een samenhangend analyserapport.
De cijfers hieronder komen uit dezelfde gecontroleerde export van de data-engineeringpipeline.</p>
<span class="chip">{escape(bundle.classification)}</span><span class="chip">Bronmodus: {escape(bundle.mode)}</span></header>
<nav><a href="#portefeuille">01 / Portefeuille</a><a href="#kaart">02 / Kaarten</a><a href="#kwaliteit">03 / Datakwaliteit</a><a href="#methode">Methodiek</a></nav>
<main><section id="portefeuille"><div class="section-title"><span class="index">01</span><h2>Woningbouwportefeuille</h2></div>
<p class="intro">Selectie: {escape(city_scope)}. Momentopname bronrun: {escape(snapshot)}.
Dit rapport is een export van deze selectie; interactieve gemeentefilters zijn beschikbaar in de lokale app.</p>
<div class="cards">{''.join(blocks)}</div><div class="findings"><h3>Wat valt op?</h3>{''.join('<p>'+escape(n)+'</p>' for n in notes)}</div>
<div class="grid">{overview}</div></section>
<section id="kaart"><div class="section-title"><span class="index">02</span><h2>Ruimtelijke samenhang</h2></div>
<p class="intro">Een bronkoppeling verklaarbaar maken: van plancontour naar BAG-object, BRK-perceel of DSO-document.
De kaart tekent alle polygononderdelen en binnenringen als contouren, in een gelijke meterschaal.</p>
<div class="grid">{maps}</div>{detail_tables}</section>
<section id="kwaliteit"><div class="section-title"><span class="index">03</span><h2>Betrouwbaarheid van de analyse</h2></div>
<p class="intro">Alle aangeleverde records binnen de selectie blijven zichtbaar in de kwaliteitsanalyse.
Een onbekende of niet bevraagde bron krijgt geen gemeten nuldekking.</p><div class="grid">{quality}</div>
<details><summary>Controleer de tellingen per kwaliteitsregel</summary>{rule_table}</details>
<details><summary>Bronstatus, unieke objecten en plan-bronrelaties</summary>{source_table}</details></section>
<section id="methode"><h2>Methodiek en grenzen</h2>
<p>Capaciteit wordt berekend op planrecordniveau, met <code>(run_id, record_id)</code> als sleutel.
Gedeelde Koppelcodes worden niet samengevoegd. READY en WARNING zijn toegelaten; REJECTED is uitgesloten uit capaciteits-KPI's.
Bronobjecten worden los geteld; een gedeeld object telt eenmaal in een unieke-objecttelling en eenmaal per koppeling in een relatietelling.</p>
<p>Null blijft onbekend. Vijfjaarsperioden worden niet naar afzonderlijke jaren verdeeld. DSO-overlap is geen inhoudelijke bevestiging.
Er zijn geen CBS-realisatiecijfers, prognoses of automatische juridische conclusies toegevoegd.
De fictieve demonstratiedata is niet geschikt voor beleidsuitspraken.</p>
<p>Dit is een portfolio-reconstructie buiten INKIS. Het rapport toont analyse, visualisatie en interpretatie,
maar claimt niet dat deze Python-interface tijdens de tender werd gebruikt. Vermeld alleen persoonlijk ontwikkelde onderdelen als eigen werk.</p>
<p>De toepassing implementeert geen authenticatie of publicatieprotocol. Een rapport op basis van echte plandata blijft intern;
ook kaartcontouren, vertrouwelijke namen, aantallen en bronrelaties kunnen gevoelige informatie prijsgeven.</p></section>
<footer>Run <code>{escape(bundle.run_id)}</code> &middot; Rapport aangemaakt {created}<br>
Gebouwd met Pandas, Shapely en Plotly. Grafieken en vectorgeometrie zijn in dit HTML-bestand opgenomen; geen externe kaartdienst.</footer></main></body></html>'''


def main() -> int:
    parser = argparse.ArgumentParser(description="Create an HTML report from one LMVW database-ready export.")
    parser.add_argument("--bundle", type=Path, default=DEMO)
    parser.add_argument("--output", type=Path, default=Path("data/reports/report.html"))
    parser.add_argument("--municipality", action="append")
    parser.add_argument("--hardness", action="append", choices=["HARD", "SOFT", "UNKNOWN"])
    parser.add_argument("--record-id", help="Optional plan record for the detail map")
    args = parser.parse_args()
    try:
        bundle = load_bundle(args.bundle)
        plans = filter_plans(bundle, args.municipality, args.hardness)
        html = make_html(bundle, plans, selected_record=args.record_id)
        args.output.parent.mkdir(parents=True, exist_ok=True)
        with args.output.open("x", encoding="utf-8") as stream:
            stream.write(html)
    except (DataError, OSError) as exc:
        parser.exit(1, f"Rapport niet gemaakt: {exc}\n")
    print(f"Rapport: {args.output.resolve()} ({len(plans)} planrecords in selectie)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
