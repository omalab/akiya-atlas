"""Refresh redistributable reference facts, with pinned source revisions and hashes.

uv run python tools/prepare_coastal_data.py
No municipal HTML is downloaded or stored by this script.
"""

from __future__ import annotations

import csv
import hashlib
import io
import json
from pathlib import Path

import httpx

COAST_REV = "a726d63745ff99cf26a03ae1c7cfb0d4f12fa517"
COAST_URL = (
    f"https://raw.githubusercontent.com/nvkelso/natural-earth-vector/{COAST_REV}"
    "/geojson/ne_10m_coastline.geojson"
)
AIRPORTS_REV = "b529623d2a0b09a9be78d37fc7a7a5e1e16e3451"
AIRPORTS_URL = (
    f"https://raw.githubusercontent.com/davidmegginson/ourairports-data/{AIRPORTS_REV}/airports.csv"
)
CODES = "KIX ITM UKB SHM TKS TAK MYJ KCZ OKJ HIJ NGO".split()
OUT = Path(__file__).resolve().parents[1] / "data" / "geo"


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    with httpx.Client(timeout=90, follow_redirects=True) as client:
        coast = client.get(COAST_URL)
        coast.raise_for_status()
        lines = []
        for feature in coast.json()["features"]:
            geom = feature["geometry"]
            parts = [geom["coordinates"]] if geom["type"] == "LineString" else geom["coordinates"]
            for part in parts:
                line = []
                for lon, lat in part:
                    if 128 <= lon <= 140 and 29 <= lat <= 38:
                        line.append([lon, lat])
                    else:
                        if len(line) > 1:
                            lines.append(line)
                        line = []
                if len(line) > 1:
                    lines.append(line)
        payload = {
            "source": COAST_URL,
            "sha256": hashlib.sha256(coast.content).hexdigest(),
            "license": "Public domain; Natural Earth 1:10m coastline",
            "bbox": [128, 29, 140, 38],
            "lines": lines,
        }
        (OUT / "coastline.json").write_text(json.dumps(payload, separators=(",", ":")) + "\n")
        # Include every Japanese scheduled-service airport: e.g. Tajima can beat ITM
        # on the north Hyogo coast. The issue's eleven airports are a required subset.
        response = client.get(AIRPORTS_URL)
        response.raise_for_status()
        airports = []
        for row in csv.DictReader(io.StringIO(response.text)):
            if (
                row["iso_country"] == "JP"
                and row["iata_code"]
                and row["scheduled_service"] == "yes"
            ):
                lon, lat = float(row["longitude_deg"]), float(row["latitude_deg"])
                airports.append(
                    {
                        "iata": row["iata_code"],
                        "name": row["name"],
                        "longitude": lon,
                        "latitude": lat,
                        "icao": row["ident"],
                        "scheduled_service": True,
                        "website": row["home_link"],
                    }
                )
        if not set(CODES) <= {r["iata"] for r in airports}:
            raise ValueError("airport reference is missing requested candidates")
        (OUT / "airports.json").write_text(
            json.dumps(
                {
                    "source": AIRPORTS_URL,
                    "sha256": hashlib.sha256(response.content).hexdigest(),
                    "license": "Public domain (OurAirports)",
                    "airports": sorted(airports, key=lambda a: a["iata"]),
                },
                indent=2,
            )
            + "\n"
        )
    print(f"Saved {len(lines)} coastal lines, {len(airports)} airports to {OUT}")


if __name__ == "__main__":
    main()
