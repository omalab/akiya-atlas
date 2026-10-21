"""Geometry, provenance, filters and true first-seen feed windows."""

from __future__ import annotations

import copy
import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from xml.etree import ElementTree as ET

import httpx
import pytest
from sitemill.models import FieldValue

from akiya_atlas import coastal
from akiya_atlas.coastal import Filters, matches, new_rows
from akiya_atlas.geo import (
    coast_distance_km,
    distance_km,
    estimated_drive_minutes,
    segment_distance_km,
)
from akiya_atlas.geocode import GSI_URL, Geocoder, address_query, choose_result, save_json
from akiya_atlas.schema import Listing

NOW = datetime(2026, 10, 21, 18, tzinfo=UTC)
ROW = {
    "id": "one",
    "muni": "海辺町",
    "no": "1",
    "deal": "sale",
    "price": 1_000_000,
    "price_text": "100万円",
    "source_url": "https://example.invalid/listing?a=1&b=2",
    "first_seen_at": (NOW - timedelta(hours=1)).isoformat(),
    "geo": {"status": "ok", "coast_km": 5, "airport_drive_minutes": 90, "airport_iata": "KCZ"},
}


def test_geodesic_distances_and_segment_projection():
    assert distance_km((0, 0), (0, 0)) == 0
    assert distance_km((0, 0), (1, 0)) == pytest.approx(111.195, abs=0.001)
    assert distance_km((0, 0), (180, 0)) == pytest.approx(20015.114, abs=0.001)
    # Interior of the arc is nearest, not either vertex.
    assert segment_distance_km((0, 1), (-1, 0), (1, 0)) == pytest.approx(111.195, abs=0.001)
    assert segment_distance_km((2, 0), (-1, 0), (1, 0)) == pytest.approx(111.195, abs=0.001)
    assert segment_distance_km((0, 1), (0, 0), (0, 0)) == distance_km((0, 1), (0, 0))
    assert segment_distance_km((180, 1), (179, 0), (-179, 0)) == pytest.approx(111.195, abs=0.001)
    assert coast_distance_km((0, 0), [[(-1, 0), (1, 0)]]) == 0
    with pytest.raises(ValueError):
        coast_distance_km((0, 0), [])
    assert estimated_drive_minutes(0) == 15
    assert estimated_drive_minutes(50) == 99
    with pytest.raises(ValueError):
        estimated_drive_minutes(float("nan"))


def test_reference_airports_and_coast_are_in_japan():
    root = Path(__file__).resolve().parents[1] / "data" / "geo"
    airports = json.loads((root / "airports.json").read_text())["airports"]
    assert set("KIX ITM UKB SHM TKS TAK MYJ KCZ OKJ HIJ NGO TJH TTJ".split()) <= {
        a["iata"] for a in airports
    }
    for a in airports:
        assert 122 < a["longitude"] < 147 and 24 < a["latitude"] < 46
        assert a["scheduled_service"]
    coast = json.loads((root / "coastline.json").read_text())["lines"]
    # Kochi airport is on the coastal plain; Nara is inland. Catch lon/lat reversal.
    assert coast_distance_km((133.67, 33.545), coast) < 5
    assert coast_distance_km((135.83, 34.68), coast) > 20


def test_filter_inclusive_boundaries_missing_prices_and_rent():
    assert matches(ROW, Filters())
    assert matches(ROW, Filters(price_cap_yen=1_000_000))
    assert not matches(ROW, Filters(max_coast_km=4.999))
    assert not matches(ROW, Filters(max_airport_minutes=89.99))
    assert not matches(ROW, Filters(price_cap_yen=999_999))
    assert not matches({**ROW, "price": None}, Filters(price_cap_yen=1_000_000))
    assert not matches({**ROW, "deal": "rent"}, Filters(price_cap_yen=1_000_000))
    assert matches({**ROW, "price": 0}, Filters(price_cap_yen=0))
    assert not matches({**ROW, "geo": {"status": "pending"}}, Filters())
    for bad in (-1, float("inf"), float("nan")):
        with pytest.raises(ValueError):
            Filters(max_coast_km=bad)


def test_new_feed_uses_first_seen_not_last_seen_and_has_no_future_items():
    stamps = [
        NOW,
        NOW - timedelta(hours=24),
        NOW - timedelta(hours=24, seconds=1),
        NOW + timedelta(seconds=1),
    ]
    rows = [
        {**ROW, "id": str(i), "first_seen_at": t.isoformat(), "updated": NOW.isoformat()}
        for i, t in enumerate(stamps)
    ]
    rows += [{**ROW, "first_seen_at": None}, {**ROW, "first_seen_at": "2026-10-21T12:00:00"}]
    assert {r["id"] for r in new_rows(rows, Filters(), NOW)} == {"0", "1"}
    assert new_rows([ROW], Filters(price_cap_yen=0), NOW) == []


def test_gsi_address_matching_rejects_centroids_wrong_and_ambiguous_places():
    def feature(title, coords=(135.78, 33.47)):
        return {"properties": {"title": title}, "geometry": {"coordinates": list(coords)}}

    query = address_query("和歌山県", "串本町", "東牟婁郡串本町大字串本")
    assert query == "和歌山県串本町串本"
    assert choose_result([feature(query)], query, "串本町")["latitude"] == 33.47
    assert choose_result([feature("和歌山県串本町")], query, "串本町") is None
    assert choose_result([feature(query)], "和歌山県串本町", "串本町") is None
    assert choose_result([feature(query), feature(query, (135, 34))], query, "串本町") is None
    assert choose_result([feature(query, (34, 200))], query, "串本町") is None


def test_geocoder_caches_success_and_no_match_and_throttles(tmp_path):
    requests, waits = [], []

    def transport(request):
        requests.append(request)
        return httpx.Response(200, json=[])

    with httpx.Client(transport=httpx.MockTransport(transport)) as client:
        coder = Geocoder(
            tmp_path / "cache.json", client=client, sleep=waits.append, clock=lambda: 0
        )
        coder.lookup("高知県海辺町東", "海辺町")
        coder.lookup("高知県海辺町東", "海辺町")
        coder.lookup("高知県海辺町西", "海辺町")
        assert len(requests) == 2 and waits == [1.0]
        assert str(requests[0].url).startswith(GSI_URL)
        reloaded = Geocoder(tmp_path / "cache.json", client=client)
        assert reloaded.lookup("高知県海辺町東", "海辺町")["status"] == "unresolved"
        assert len(requests) == 2


def test_http_failures_are_retryable_not_negative_cached(tmp_path):
    with httpx.Client(transport=httpx.MockTransport(lambda r: httpx.Response(429))) as client:
        coder = Geocoder(tmp_path / "cache.json", client=client)
        with pytest.raises(httpx.HTTPStatusError):
            coder.lookup("高知県海辺町東", "海辺町")
        assert not coder.cache


def test_export_json_rss_parity_and_escaping(tmp_path, monkeypatch):
    row = {**ROW, "muni": "A&B <C>"}
    monkeypatch.setattr(coastal, "tracker_rows", lambda ws, ds: [row])
    ws = SimpleNamespace(site=SimpleNamespace(base_url="https://example.invalid"))
    report = coastal.export(ws, None, tmp_path, filters=Filters(), now=NOW)
    assert report == {"eligible": 1, "matched": 1, "new_24h": 1}
    feed = json.loads((tmp_path / "new.json").read_text())
    rss = ET.parse(tmp_path / "new.rss")
    assert feed["listings"][0]["id"] == rss.findtext("channel/item/guid")
    assert rss.findtext("channel/item/title") == "A&B <C> — 1"
    assert rss.findtext("channel/item/link") == ROW["source_url"]
    coastal.export(ws, None, tmp_path, filters=Filters(price_cap_yen=0), now=NOW)
    assert ET.parse(tmp_path / "new.rss").find("channel/item") is None


def test_changed_address_does_not_reuse_old_geocoding(tmp_path, monkeypatch):
    listing = Listing(
        record_id="id",
        source_id="s",
        municipality_code="392014",
        listing_no="1",
        source_url="https://example.invalid",
        address=FieldValue(value="海辺町東", quote="海辺町東", status="parsed"),
    )
    muni = SimpleNamespace(name="海辺町", prefecture="高知県")
    monkeypatch.setattr(coastal, "candidates", lambda ws, ds: [(muni, listing)])
    monkeypatch.setattr("akiya_atlas.pages.search_row", lambda m, ls: {})
    ws = SimpleNamespace(data_dir=tmp_path)
    cache = {"id": {"status": "ok", "query": "高知県海辺町東", "reference": "missing_reference"}}
    save_json(tmp_path / "geo" / "listings.json", copy.deepcopy(cache))
    assert coastal.tracker_rows(ws, None)[0]["geo"]["status"] == "ok"
    listing.address.value = "海辺町西"
    assert coastal.tracker_rows(ws, None)[0]["geo"]["status"] == "pending"
