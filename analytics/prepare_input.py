"""Create an explicit-CRS COPY of a raw LMVW CSV for Part 1.

This is a format/metadata helper, not a business-data cleaner. It does not repair
polygons, change counts, remove rejected records or infer a CRS from coordinates.
An existing, non-empty and conflicting CRS stops the operation.
"""
from __future__ import annotations

import argparse
import csv
from pathlib import Path


def prepare_csv(source: Path, target: Path, *, crs: str, wkt_column: str = "Polygon_WKT",
                delimiter: str = ";") -> int:
    source, target = source.resolve(), target.resolve()
    if source == target or target.exists():
        raise ValueError("Kies een nieuw uitvoerbestand; bronbestanden worden niet overschreven.")
    if crs not in {"EPSG:28992", "EPSG:4326"}:
        raise ValueError("Ondersteund: EPSG:28992 (RD) of EPSG:4326 (lengte/breedtegraad).")
    if len(delimiter) != 1:
        raise ValueError("Het CSV-scheidingsteken moet precies een teken zijn.")
    csv.field_size_limit(100 * 1024 * 1024)
    with source.open(encoding="utf-8-sig", newline="") as stream:
        reader = csv.DictReader(stream, delimiter=delimiter)
        headers = reader.fieldnames or []
        if not headers or len(set(headers)) != len(headers) or any(not h.strip() for h in headers):
            raise ValueError("Ontbrekende of dubbele kolomnamen.")
        if any("**" in h or "&#" in h for h in headers):
            raise ValueError("De header bevat Markdown/HTML-opmaak. Exporteer opnieuw uit het bronbestand.")
        if wkt_column not in headers:
            raise ValueError("De opgegeven WKT-kolom ontbreekt; controleer ook het scheidingsteken.")
        rows = list(reader)
    if not rows:
        raise ValueError("Het bronbestand bevat geen planrecords.")
    for row in rows:
        if None in row or any(v is None for v in row.values()):
            raise ValueError("Een CSV-rij heeft een ander aantal velden dan de header.")
        previous = row.get("CRS", "").strip()
        if previous and previous != crs:
            raise ValueError("Bestaande CRS wijkt af; er wordt niet stilzwijgend een ander label gegeven.")
    # The pipeline currently consumes the fixed Polygon_WKT + CRS names.
    # Selecting a different source WKT is explicit. Preserve the old geometry too.
    if wkt_column != "Polygon_WKT" and "Polygon_WKT" in headers:
        if "Original_Polygon_WKT" in headers:
            raise ValueError("Original_Polygon_WKT bestaat al; kies een onbewerkte bronkopie.")
        headers.append("Original_Polygon_WKT")
        for row in rows:
            row["Original_Polygon_WKT"] = row["Polygon_WKT"]
    for col in ("Polygon_WKT", "CRS"):
        if col not in headers:
            headers.append(col)
    for row in rows:
        row["Polygon_WKT"] = row[wkt_column]
        row["CRS"] = crs
    target.parent.mkdir(parents=True, exist_ok=True)
    # Exclusive creation prevents a racing command from overwriting an existing copy.
    with target.open("x", encoding="utf-8-sig", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=headers, delimiter=delimiter)
        writer.writeheader(); writer.writerows(rows)
    return len(rows)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", type=Path)
    parser.add_argument("target", type=Path)
    parser.add_argument("--crs", required=True, choices=["EPSG:28992", "EPSG:4326"],
                        help="Explicit source metadata declaration; verify against the source specification.")
    parser.add_argument("--wkt-column", default="Polygon_WKT")
    parser.add_argument("--delimiter", default=";")
    args = parser.parse_args()
    try:
        count = prepare_csv(args.source, args.target, crs=args.crs, wkt_column=args.wkt_column, delimiter=args.delimiter)
    except (ValueError, OSError) as exc:
        parser.exit(1, f"Invoer niet voorbereid: {exc}\n")
    print(f"Kopie gemaakt: {args.target}; {count} records; CRS={args.crs}. Woninggegevens niet aangepast.")
    print("Voer nu de afzonderlijke kwaliteitscontrole uit. Niet iedere bronfout is hiermee opgelost.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
