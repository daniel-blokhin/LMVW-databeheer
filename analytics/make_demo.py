"""Rebuild the 36-plan SYNTHETIC report dataset through the simplified Part 1.

Only this optional regeneration script imports pipeline. The report itself is
independent. No real plans or live APIs are used. Existing demo is not replaced
unless --replace is explicit. Requires Part 1's requirements.txt.
"""
from __future__ import annotations

import argparse
import copy
import csv
import json
from pathlib import Path
import shutil
import tempfile
import uuid


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--replace", action="store_true")
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    demo = Path(__file__).parent / "demo"
    destination = demo / "database_ready"
    if destination.exists() and not args.replace:
        parser.exit(1, "Demo bestaat al. Gebruik --replace uitsluitend om de synthetische demo opnieuw op te bouwen.\n")
    try:
        import yaml
        from shapely.geometry import Point, box, mapping
        from pipeline.settings import load_config
        from pipeline.geospatial import RD_URI, geometry_key
        from pipeline.run import run_pipeline
    except ImportError:
        parser.exit(1, "Regenereren vereist de vereenvoudigde pipeline/ en requirements.txt van deel 1. "
                       "De meegeleverde demo kan wel zonder die stap worden gebruikt.\n")
    config = copy.deepcopy(load_config(root / "config.yaml").values)
    names = config["mapping"]["fields"]
    groups = config["mapping"]["groups"]
    phases = [str(y) for y in range(2026, 2036)] + ["2036 t/m 2040", "2041 t/m 2045"]
    headers = list(names.values()) + phases + [v for g in groups.values() for v in g.values()] + ["Polygon_WKT", "CRS"]
    cities = ["Demo Waterdam", "Demo Heuvelstad", "Demo Polderveen"]
    codes = ["1A. Onherroepelijk", "1B. Uitwerking", "2A. Vastgesteld", "2B. Uitwerking",
             "1C. Wijziging nodig", "2C. Wijziging nodig", "3. In voorbereiding", "4A. Visie", "4B. Idee"]
    stamp = "2026-10-16T09:00:00Z"
    dso = {"synthetic": True, "retrieved_at": stamp, "areas": {}, "geometries": {}, "document_structures": {}}
    source_features = {"bag_panden": [], "bag_vbo": [], "brk": []}
    plans = []

    def feature(kind, index, props, geom):
        return {"type": "Feature", "id": str(uuid.uuid5(uuid.NAMESPACE_DNS, f"lmvw-synthetic-{kind}-{index}")),
                "properties": props, "geometry": mapping(geom)}

    for city in range(3):
        base_x, base_y = 150000 + city * 1400, 450000 + city * 900
        native = f"/akn/nl/act/gm000{city}/2026/demo-regeling"
        gid = f"SYN-REGION-{city}"
        dso["geometries"][gid] = mapping(box(base_x - 30, base_y - 30, base_x + 780, base_y + 550))
        dso["document_structures"][native] = {"kop": f"Synthetische regeling {cities[city]}",
                                               "inhoud": "Fictieve voorbeeldtekst. Geen juridische werking."}
        regulation = {"identificatie": native, "officieleTitel": f"Demo omgevingsplan {cities[city]}",
                      "type": {"waarde": "Omgevingsplan"}, "aangeleverdDoorEen": {"naam": cities[city], "code": f"gm000{city}"},
                      "geregistreerdMet": {"beginGeldigheid": "2026-01-01"},
                      "_embedded": {"regelingsgebied": [{"geometrieIdentificatie": gid}]}}
        for j in range(12):
            i = city * 12 + j
            gross = [24, 38, 16, 60, 84, 120, 48, 32, 72, 96, 20, 44][j]
            demolition = gross + 5 if i == 2 else [0, 4, 0, 6][j % 4]
            x = base_x + (j % 4) * 200
            y = base_y + (j // 4) * 180
            # Two different plan records sharing the same area key/contour.
            if i == 1:
                x, y = base_x, base_y
            geom = box(x, y, x + 120, y + 100)
            row = {h: "0" for h in headers}
            attributes = {"municipality": cities[city], "confidential": "Ja" if j % 9 in (6, 7, 8) else "Nee",
                          "plan_name": f"Demoplan {i+1:02d}", "koppelcode": f"DEMO_{0 if i==1 else i:03d}",
                          "gross_capacity": gross, "demolition": demolition, "net_capacity_reported": gross-demolition,
                          "plan_type": config["quality"]["allowed_plan_types"][j % 6], "plan_status": codes[j % 9],
                          "temporary_homes": gross // 4 if j % 3 == 0 else 0}
            row.update({names[k]: str(v) for k, v in attributes.items()})
            row["Polygon_WKT"], row["CRS"] = geom.wkt, "EPSG:28992"
            first = i % 12
            row[phases[first]], row[phases[(first + 1) % 12]] = str(gross // 2), str(gross - gross // 2)
            single, unknown = gross // 3, gross // 12
            for key, count in [("single_family", single), ("multi_family", gross-single-unknown), ("unknown", unknown)]:
                row[groups["housing_type"][key]] = str(count)
            housing = {"corporation_low_rent": gross//4, "corporation_middle_rent": gross//5,
                       "affordable_purchase": gross//3}
            housing["expensive_purchase"] = gross - sum(housing.values())
            for key, count in housing.items():
                row[groups["tenure_price"][key]] = str(count)
            row[groups["senior_housing"]["step_free_not_clustered"]] = str(gross//10)
            # Six different blocking failures and two missing-value warnings.
            if i == 4: row[groups["housing_type"]["unknown"]] = str(unknown + 3)
            if i == 9: row[names["confidential"]] = ""
            if i == 14: row["Polygon_WKT"] = "NOT_A_POLYGON"
            if i == 19: row[names["net_capacity_reported"]] = str(gross + 9)
            if i == 24: row[names["plan_type"]] = "Onbekende plantypecode"
            if i == 29: row[phases[first]] = "veel"
            if i == 31: row[groups["senior_housing"]["other_senior"]] = ""
            if i == 33: row[phases[first]] = ""
            plans.append(row)
            for b in range(2):
                n = i * 2 + b + 1
                pand_id = f"000010{n:010d}"
                gx = x + 15 + b * 55
                building = box(gx, y + 20, gx + 30, y + 60)
                if i == 0 and b == 1:
                    building = box(x + 145, y + 20, x + 175, y + 60)  # official parent outside plan
                p = {"identificatie": pand_id, "status": "Pand in gebruik" if j % 2 else "Bouw gestart",
                     "bouwjaar": 2000+j, "aantal_verblijfsobjecten": 2, "gebruiksdoel": ["woonfunctie"],
                     "documentdatum": "2026-01-01", "documentnummer": f"SYN-P-{n}"}
                source_features["bag_panden"].append(feature("pand", n, p, building))
                for v in range(2):
                    vnum = (n-1)*2+v+1
                    p = {"identificatie": f"000001{vnum:010d}", "status": "Verblijfsobject in gebruik",
                         "gebruiksdoel": ["woonfunctie"], "oppervlakte": 65 + j, "huisnummer": vnum,
                         "openbare_ruimte_naam": "Fictieve straat", "postcode": "0000AA",
                         "documentdatum": "2026-01-01", "documentnummer": f"SYN-V-{vnum}", "pand": [pand_id]}
                    source_features["bag_vbo"].append(feature("vbo", vnum, p, Point(gx + 8+v*10, y + 35)))
            for b in range(2):
                n = i*2+b+1
                parcel = box(x-10+b*75, y-10, x+65+b*75, y+115)
                p = {"identificatie_namespace": "SYNTHETIC.BRK", "identificatie_lokaal_id": f"DEMO-PERCEEL-{n}",
                     "kadastrale_gemeente_code": f"D00{city}", "kadastrale_gemeente_waarde": cities[city],
                     "sectie": "A", "perceelnummer": n, "kadastrale_grootte_waarde": parcel.area,
                     "soort_grootte_waarde": "Vastgesteld", "status_historie_waarde": "Actueel"}
                source_features["brk"].append(feature("brk", n, p, parcel))
            key = geometry_key(geom)
            area = dso["areas"].setdefault(key, {"regelingen": [regulation], "omgevingsvergunningen": []})
            permit = {"identificatie": f"/akn/nl/act/gm000{city}/2026/demo-permit-{i}",
                      "opschrift": f"Synthetisch document bij demoplan {i+1:02d}", "type": "Omgevingsvergunning"}
            if i % 3:
                geo_id = f"SYN-PERMIT-{i}"
                location = box(x+200,y+200,x+220,y+220) if i % 7 == 0 else box(x+10,y+10,x+90,y+80)
                dso["geometries"][geo_id] = mapping(location)
                permit["_embedded"] = {"vergunningsgebied": [{"geometrieIdentificatie": geo_id}]}
            area["omgevingsvergunningen"].append(permit)
    with tempfile.TemporaryDirectory(prefix="lmvw-synthetic-") as temp:
        temp = Path(temp)
        inputs = temp / "input"
        api = inputs / "api"
        api.mkdir(parents=True)
        with (inputs / "plans.csv").open("w", encoding="utf-8", newline="") as stream:
            writer = csv.DictWriter(stream, fieldnames=headers, delimiter=";")
            writer.writeheader(); writer.writerows(plans)
        for name, features in source_features.items():
            (api / f"{name}.json").write_text(json.dumps({"synthetic": True, "retrieved_at": stamp, "content_crs": RD_URI,
                    "data": {"type": "FeatureCollection", "features": features}}, indent=2), encoding="utf-8")
        (api / "dso.json").write_text(json.dumps(dso, indent=2), encoding="utf-8")
        config["input"] = {"plans": str(inputs / "plans.csv"), "delimiter": ";", "sheet": "Planlijst"}
        config["sources"].update(mode="fixtures", fixtures_dir=str(api), bag=True, brk=True, dso=True)
        config["snapshot_utc"] = stamp
        config_path = temp / "demo.yaml"
        config_path.write_text(yaml.safe_dump(config, allow_unicode=True), encoding="utf-8")
        result = run_pipeline(config_path, output_dir=temp / "runs")
        if destination.exists(): shutil.rmtree(destination)
        shutil.copytree(result.bundle, destination)
        # Small raw CSV included for transparency; fixture JSON is reproducible from this script.
        shutil.copyfile(inputs / "plans.csv", demo / "plans_input.csv")
        (demo / "generation.json").write_text(json.dumps({"synthetic": True, "generator": "analytics.make_demo",
                    "counts": result.counts, "status": result.status,
                    "notes": "All plans and source objects are synthetic. Generated by the unchanged Part 1 pipeline."}, indent=2), encoding="utf-8")
        print(json.dumps(result.counts))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
