"""Kansai/Shikoku tracker: offline publication over cached geographical facts."""

from __future__ import annotations

import json
import math
from collections import Counter
from dataclasses import asdict, dataclass
from datetime import UTC, datetime, timedelta
from email.utils import format_datetime
from pathlib import Path
from typing import Any
from xml.etree import ElementTree as ET

import httpx
from sitemill.models import utcnow

from akiya_atlas.geo import coast_distance_km, distance_km, estimated_drive_minutes
from akiya_atlas.geocode import Geocoder, address_query, save_json

# Coastal prefectures first; every municipality in all eleven prefectures is included.
PREFECTURES = (
    "wakayama",
    "kochi",
    "tokushima",
    "ehime",
    "kagawa",
    "mie",
    "hyogo",
    "kyoto",
    "osaka",
    "nara",
    "shiga",
)
DRIVE_METHOD = "ceil(air_distance_km * 1.4 / 50 * 60 + 15)"
NOTICE = (
    "所在地の地区代表点と概略海岸線による目安です。砂浜・海への道・正確な物件位置を示しません。"
    "空港時間は直線距離×1.4÷50km/h＋15分の推定で、道路・橋・フェリー・渋滞を考慮しません。"
    "島や海峡をまたぐ場合は実際の所要時間と大きく異なります。現地と経路を必ず確認してください。"
)


@dataclass(frozen=True)
class Filters:
    max_coast_km: float = 5
    max_airport_minutes: float = 90
    price_cap_yen: int | None = None

    def __post_init__(self) -> None:
        for value in (self.max_coast_km, self.max_airport_minutes, self.price_cap_yen):
            if value is not None and (not math.isfinite(value) or value < 0):
                raise ValueError("filters must be finite and nonnegative")


def matches(row: dict, filters: Filters) -> bool:
    geo = row.get("geo") or {}
    if geo.get("status") != "ok":
        return False
    if geo["coast_km"] > filters.max_coast_km:
        return False
    if geo["airport_drive_minutes"] > filters.max_airport_minutes:
        return False
    if filters.price_cap_yen is not None:
        if row.get("deal") not in ("sale", "both") or row.get("price") is None:
            return False
        if row["price"] > filters.price_cap_yen:
            return False
    return True


def first_seen(row: dict) -> datetime | None:
    try:
        stamp = datetime.fromisoformat(row.get("first_seen_at") or "")
        return stamp.astimezone(UTC) if stamp.tzinfo else None
    except ValueError:
        return None


def new_rows(rows: list[dict], filters: Filters, now: datetime) -> list[dict]:
    cutoff = now - timedelta(hours=24)
    return sorted(
        (
            r
            for r in rows
            if matches(r, filters)
            and (stamp := first_seen(r)) is not None
            and cutoff <= stamp <= now
        ),
        key=first_seen,
        reverse=True,
    )


def _query(muni: Any, listing: Any) -> str | None:
    return (
        address_query(muni.prefecture, muni.name, listing.address.value)
        if listing.address.ok
        else None
    )


def reference_key(directory: Path) -> str:
    parts = []
    for name in ("coastline", "airports"):
        path = directory / f"{name}.json"
        if not path.exists():
            return "missing_reference"
        parts.append(json.loads(path.read_text())["sha256"][:12])
    return "/".join(parts)


def candidates(ws: Any, ds: Any) -> list[tuple[Any, Any]]:
    # Reuse publication exclusions: active, nonduplicate, crawlable and no takedowns.
    from akiya_atlas.pages import hidden_paths, visible_listings
    from akiya_atlas.service import crawls_listings

    hidden = hidden_paths(ws)
    return [
        (muni, listing)
        for pref in PREFECTURES
        for muni in ds.municipalities_in(pref)
        if crawls_listings(ds.by_source[muni.id])
        for listing in visible_listings(muni, ds.listings_for(muni, active_only=True), hidden)
    ]


def enrich(
    ws: Any, ds: Any, *, limit: int | None = None, source_ids: set[str] | None = None
) -> dict:
    directory = ws.data_dir / "geo"
    coast = json.loads((directory / "coastline.json").read_text())["lines"]
    airports = json.loads((directory / "airports.json").read_text())["airports"]
    path = directory / "listings.json"
    existing = json.loads(path.read_text()) if path.exists() else {}
    reference = reference_key(directory)
    rows = candidates(ws, ds)
    if source_ids:
        rows = [(m, ls) for m, ls in rows if ls.source_id in source_ids]
    if limit is not None:
        rows = rows[:limit]
    counts: Counter = Counter()
    with httpx.Client(
        timeout=30,
        headers={"User-Agent": "AkiyaAtlasCoastal/1.0 (https://github.com/omalab/akiya-atlas)"},
    ) as client:
        geocoder = Geocoder(directory / "geocodes.json", client=client)
        for muni, listing in rows:
            query = _query(muni, listing)
            point = None
            result: dict = {"status": "missing_address", "query": query}
            if listing.longitude is not None and listing.latitude is not None:
                point = (listing.longitude, listing.latitude)
                result.update(provider="listing", precision="source_coordinates")
            elif query:
                try:
                    location = geocoder.lookup(query, muni.name)
                    result.update(location, precision="district")
                    if location["status"] == "ok":
                        point = (location["longitude"], location["latitude"])
                except (httpx.HTTPError, ValueError, TypeError, KeyError):
                    result["status"] = "geocoder_error"
            if point:
                airport = min(
                    airports, key=lambda a: distance_km(point, (a["longitude"], a["latitude"]))
                )
                air_distance = distance_km(point, (airport["longitude"], airport["latitude"]))
                result.update(
                    status="ok",
                    longitude=point[0],
                    latitude=point[1],
                    coast_km=coast_distance_km(point, coast),
                    airport_iata=airport["iata"],
                    airport_name=airport["name"],
                    airport_km=air_distance,
                    airport_drive_minutes=estimated_drive_minutes(air_distance),
                    drive_method=DRIVE_METHOD,
                )
            result["checked_at"] = utcnow().isoformat()
            result["reference"] = reference
            existing[listing.record_id] = result
            counts[result["status"]] += 1
            save_json(path, existing)
        counts["geocoder_requests"] = geocoder.requests
    return dict(counts)


def tracker_rows(ws: Any, ds: Any) -> list[dict]:
    from akiya_atlas.pages import search_row

    path = ws.data_dir / "geo" / "listings.json"
    cached = json.loads(path.read_text()) if path.exists() else {}
    reference = reference_key(ws.data_dir / "geo")
    rows = []
    for muni, listing in candidates(ws, ds):
        geo = cached.get(listing.record_id, {"status": "pending"})
        if geo.get("query") != _query(muni, listing):
            geo = {"status": "pending"}
        if geo.get("reference") != reference:
            geo = {"status": "pending"}
        if (
            listing.longitude is not None
            and listing.latitude is not None
            and geo.get("provider") != "listing"
        ):
            geo = {"status": "pending"}
        if geo.get("provider") == "listing" and (geo.get("longitude"), geo.get("latitude")) != (
            listing.longitude,
            listing.latitude,
        ):
            geo = {"status": "pending"}
        rows.append(
            {
                **search_row(muni, listing),
                "title": f"{muni.name} · {listing.listing_no}",
                "first_seen_at": listing.first_seen_at,
                "source_url": listing.primary_url,
                "geo": geo,
            }
        )
    return rows


def payload(rows: list[dict], filters: Filters, now: datetime) -> dict:
    return {
        "generated_at": now.isoformat(),
        "filters": asdict(filters),
        "notice": NOTICE,
        "total": len(rows),
        "geo_status": dict(Counter(r["geo"]["status"] for r in rows)),
        "listings": [r for r in rows if matches(r, filters)],
    }


def export(ws: Any, ds: Any, out: Path, *, filters: Filters, now: datetime) -> dict:
    rows = tracker_rows(ws, ds)
    return export_rows(rows, ws.site.base_url, out, filters=filters, now=now)


def export_rows(
    rows: list[dict], base_url: str, out: Path, *, filters: Filters, now: datetime
) -> dict:
    """Publish one consistent snapshot to both feeds and the filtered data file."""
    result = payload(rows, filters, now)
    save_json(out / "listings.json", result)
    fresh = new_rows(rows, filters, now)
    save_json(out / "new.json", {**result, "listings": fresh, "window_hours": 24})
    rss = ET.Element("rss", version="2.0")
    channel = ET.SubElement(rss, "channel")
    for key, value in {
        "title": "Coastal Kansai/Shikoku akiya — new in 24 hours",
        "link": base_url.rstrip("/") + "/coastal/",
        "description": f"Filters: {asdict(filters)}. {NOTICE}",
        "lastBuildDate": format_datetime(now.astimezone(UTC), usegmt=True),
    }.items():
        ET.SubElement(channel, key).text = value
    for row in fresh:
        item = ET.SubElement(channel, "item")
        for key, value in {
            "title": f"{row['muni']} — {row['no']}",
            "link": row["source_url"],
            "guid": row["id"],
            "pubDate": format_datetime(first_seen(row), usegmt=True),
            "description": (
                f"Coast {row['geo']['coast_km']:.1f} km; {row['geo']['airport_iata']} "
                f"~{row['geo']['airport_drive_minutes']} min; {row['price_text']}."
            ),
        }.items():
            node = ET.SubElement(item, key)
            node.text = value
            if key == "guid":
                node.set("isPermaLink", "false")
    (out / "new.rss").write_bytes(ET.tostring(rss, encoding="utf-8", xml_declaration=True))
    return {"eligible": len(rows), "matched": len(result["listings"]), "new_24h": len(fresh)}
