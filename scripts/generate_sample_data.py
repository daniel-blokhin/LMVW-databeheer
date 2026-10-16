"""Regenerate artificial fixtures; no project data, personal data or API keys."""
from __future__ import annotations

import csv
from pathlib import Path

import yaml
from shapely.geometry import Point, box, mapping

from lmvw_pipeline.common import write_json
from lmvw_pipeline.geometry import RD, RD_URI, geometry_key, rd_wkt

ROOT = Path(__file__).resolve().parents[1]
WHEN = "2026-10-16T09:00:00Z"


def generate(destination: Path = ROOT / "data" / "sample") -> None:
    destination.mkdir(parents=True, exist_ok=True)
    api = destination / "api"
    api.mkdir(exist_ok=True)
    columns = yaml.safe_load((ROOT / "configs" / "columns.yaml").read_text())
    scalar, groups = columns["fields"], columns["groups"]
    periods = [str(y) for y in range(2026, 2036)] + ["2036 t/m 2040", "2041 t/m 2045"]
    headers = list(scalar.values()) + periods + [h for group in groups.values() for h in group.values()] + ["Polygon_WKT", "CRS"]
    a, b, h = box(150000, 450000, 150100, 450100), box(150080, 450000, 150180, 450100), box(150400, 450000, 150450, 450050)
    def plan(name: str, code: str, geom, gross: int = 10, demolition: int = 0, confidential: str = "Nee") -> dict:
        row = {header: 0 for header in headers}
        values = {"municipality": "Voorbeeldgemeente", "plan_name": name, "koppelcode": code,
                  "confidential": confidential, "gross_capacity": gross, "demolition": demolition,
                  "net_capacity_reported": gross - demolition, "plan_status": "1A. Onherroepelijk",
                  "plan_type": "Herstructurering", "temporary_homes": 0}
        row.update({scalar[key]: value for key, value in values.items()})
        row.update({"2026": gross, groups["housing_type"]["single_family"]: gross,
                    groups["tenure_price"]["affordable_purchase"]: gross,
                    "Polygon_WKT": rd_wkt(geom), "CRS": RD})
        return row
    rows = [plan('Synthetic canal, "phase A"', "SYN_A", a),
            plan("Synthetic confidential courtyard", "SYN_B", b, 8, confidential="Ja"),
            plan("Synthetic canal phase B", "SYN_A", a, 5),
            plan("Synthetic replacement (negative net)", "SYN_H", h, 2, demolition=5),
            plan("Deliberate wrong housing sum", "SYN_E1", a),
            plan("Deliberate unknown confidentiality", "SYN_E2", b, confidential=""),
            plan("Deliberate invalid geometry", "SYN_E3", a),
            plan("Deliberate non-integer count", "SYN_E4", a)]
    rows[1][scalar["plan_status"]] = "3. In voorbereiding"
    rows[4][groups["housing_type"]["single_family"]] = 9
    rows[6]["Polygon_WKT"] = "POLYGON ((150000 450000,150100 450100,150000 450100,150100 450000,150000 450000))"
    rows[7][scalar["gross_capacity"]] = "ten"
    # Keep a five-year bucket explicit rather than pretending it is a single year.
    rows[2]["2026"], rows[2]["2036 t/m 2040"] = 0, 5
    with (destination / "plans.csv").open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=headers, delimiter=";", lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)

    def fid(n: int) -> str:
        return f"00000000-0000-4000-8000-{n:012d}"
    def bagid(n: int) -> str:
        return f"000010000000{n:04d}"
    def vboid(n: int) -> str:
        return f"000001000000{n:04d}"
    def feature(identifier: str, geometry, properties: dict) -> dict:
        return {"type": "Feature", "id": identifier, "properties": properties, "geometry": mapping(geometry)}
    shapes = [box(150010, 450010, 150030, 450030), box(150900, 450000, 150920, 450020),
              box(150090, 450050, 150110, 450070), box(150100, 450010, 150115, 450030),
              box(150410, 450010, 150430, 450030)]
    panden = [feature(fid(i), geom, {"identificatie": bagid(i), "status": "Pand in gebruik", "bouwjaar": 2000 + i,
                                    "aantal_verblijfsobjecten": 1, "gebruiksdoel": ["woonfunctie"],
                                    "documentdatum": "2026-01-01", "documentnummer": f"SYN-P-{i}"})
              for i, geom in enumerate(shapes, 1)]
    parent_url = "https://api.pdok.nl/kadaster/bag/ogc/v2/collections/pand/items/" + fid(2)
    vbo_cases = [(Point(150020, 450020), [bagid(1)], "woonfunctie"),
                 (Point(150040, 450040), [{"href": parent_url}], "woonfunctie"),
                 (Point(150100, 450060), [fid(3), bagid(4)], "woonfunctie"),
                 (Point(150420, 450020), [bagid(5)], "woonfunctie"),
                 (Point(150020, 450080), [bagid(1)], "kantoorfunctie"),
                 (Point(152000, 452000), [bagid(1)], "woonfunctie")]
    vbos = [feature(fid(100 + i), point, {"identificatie": vboid(i), "status": "Verblijfsobject in gebruik",
                                        "gebruiksdoel": [goal], "oppervlakte": 75, "huisnummer": i,
                                        "openbare_ruimte_naam": "Synthetische Straat", "postcode": "0000AA",
                                        "documentdatum": "2026-01-01", "documentnummer": f"SYN-V-{i}", "pand": parents})
            for i, (point, parents, goal) in enumerate(vbo_cases, 1)]
    parcel_shapes = [box(149980, 449980, 150080, 450120), box(150080, 450000, 150150, 450100),
                     box(150100, 450080, 150150, 450100), box(150400, 450000, 150450, 450050)]
    parcels = [feature(fid(200 + i), geom, {"identificatie_namespace": "SYNTHETIC.BRK", "identificatie_lokaal_id": f"SYN-PARCEL-{i}",
                                          "kadastrale_gemeente_code": "SYN00", "kadastrale_gemeente_waarde": "Voorbeeldgemeente",
                                          "sectie": "A", "perceelnummer": i, "kadastrale_grootte_waarde": geom.area,
                                          "soort_grootte_waarde": "Vastgesteld", "status_historie_waarde": "Actueel"})
               for i, geom in enumerate(parcel_shapes, 1)]
    for name, data in (("bag_panden", panden), ("bag_vbo", vbos), ("brk", parcels)):
        write_json(api / (name + ".json"), {"synthetic": True, "retrieved_at": WHEN, "content_crs": RD_URI,
                                             "data": {"type": "FeatureCollection", "features": data, "links": []}})
    regeling_id = "/akn/nl/act/gm0000/2026/synthetic-omgevingsplan"
    regeling = {"identificatie": regeling_id, "officieleTitel": "Synthetisch omgevingsplan - geen juridische werking",
                "type": {"waarde": "Omgevingsplan"}, "aangeleverdDoorEen": {"naam": "Voorbeeldgemeente", "code": "gm0000"},
                "geregistreerdMet": {"beginGeldigheid": "2026-01-01"},
                "_embedded": {"regelingsgebied": [{"geometrieIdentificatie": "SYN-GEO-WIDE"}]}}
    permit = {"identificatie": "/akn/nl/act/gm0000/2026/synthetic-permit", "opschrift": "Synthetische vergunning",
              "type": "Omgevingsvergunning", "_embedded": {"vergunningsgebied": [{"geometrieIdentificatie": "SYN-GEO-PERMIT"}]}}
    unknown = {"identificatie": "/akn/nl/act/gm0000/2026/synthetic-unverified", "opschrift": "Kandidaat zonder geometrie",
               "type": "Omgevingsvergunning"}
    outside = {"identificatie": "/akn/nl/act/gm0000/2026/synthetic-outside", "opschrift": "Buiten plangebied, geen bewijs",
               "type": "Omgevingsvergunning", "_embedded": {"vergunningsgebied": [{"geometrieIdentificatie": "SYN-GEO-OUTSIDE"}]}}
    rp = {"id": "NL.IMRO.0000.SYNTHETIC-0001", "naam": "Synthetisch ruimtelijk plan", "type": "bestemmingsplan",
          "planstatusInfo": {"planstatus": "vastgesteld", "datum": "2026-01-01"}, "geometrie": mapping(b)}
    payload = {"synthetic": True, "retrieved_at": WHEN,
               "areas": {geometry_key(a): {"regelingen": [regeling], "omgevingsvergunningen": [permit], "plannen": []},
                         geometry_key(b): {"regelingen": [regeling], "omgevingsvergunningen": [unknown, outside], "plannen": [rp]},
                         geometry_key(h): {"regelingen": [regeling], "omgevingsvergunningen": [], "plannen": []}},
               "geometries": {"SYN-GEO-WIDE": mapping(box(149900, 449900, 150600, 450200)),
                              "SYN-GEO-PERMIT": mapping(box(150010, 450010, 150050, 450050)),
                              "SYN-GEO-OUTSIDE": mapping(box(150900, 450900, 150910, 450910))},
               "document_structures": {regeling_id: {"_embedded": {"documentComponenten": [
                   {"kop": "<h1>Voorbeeldregeling</h1>", "inhoud": "<p>Geen juridisch document &amp; geen echte publicatie.</p>",
                    "_embedded": {"documentComponenten": [
                        {"kop": "Artikel 1", "inhoud": "<p>Herhaalde clausule, met een komma.</p>"},
                        {"kop": "Artikel 2", "inhoud": "<p>Herhaalde clausule, met een komma.</p>"}]}}]}}}}
    write_json(api / "dso.json", payload)


if __name__ == "__main__":
    generate()
