"""One GSI request at a time, cached by address; builds never use the network."""

from __future__ import annotations

import json
import re
import time
import unicodedata
from pathlib import Path
from typing import Any

import httpx

from akiya_atlas.geo import valid_point

GSI_URL = "https://msearch.gsi.go.jp/address-search/AddressSearch"


def normalized(text: str) -> str:
    # GSI omits county names, 大字 and 字. Do not remove municipality/district names.
    text = unicodedata.normalize("NFKC", text)
    return re.sub(r"[^都道府県市町村]+郡|大字|字|\s+", "", text)


def address_query(prefecture: str, municipality: str, address: str) -> str:
    if municipality not in address:
        address = municipality + address
    if not address.startswith(prefecture):
        address = prefecture + address
    return normalized(address)


def choose_result(results: list[dict], query: str, municipality: str) -> dict | None:
    """Accept an unambiguous district match, never an implicit municipal centroid."""
    query = normalized(query)
    if query.endswith(municipality):
        return None
    matches = []
    for row in results:
        title = row.get("properties", {}).get("title", "")
        coords = row.get("geometry", {}).get("coordinates", [])
        if normalized(title) != query or len(coords) != 2:
            continue
        point = tuple(float(x) for x in coords)
        if valid_point(point):
            matches.append({"longitude": point[0], "latitude": point[1], "label": title})
    unique = {(m["longitude"], m["latitude"]) for m in matches}
    return matches[0] if len(unique) == 1 else None


def save_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    tmp.replace(path)


class Geocoder:
    def __init__(self, path: Path, *, client: httpx.Client, sleep=time.sleep, clock=time.monotonic):
        self.path, self.client, self.sleep, self.clock = path, client, sleep, clock
        self.cache = json.loads(path.read_text()) if path.exists() else {}
        self.last_request: float | None = None
        self.requests = 0

    def lookup(self, query: str, municipality: str) -> dict:
        if query in self.cache:
            return self.cache[query]
        if self.last_request is not None:
            self.sleep(max(0, 1.0 - (self.clock() - self.last_request)))
        self.last_request = self.clock()
        self.requests += 1
        # Transient errors are not cached as "no result". The next run can retry them.
        response = self.client.get(GSI_URL, params={"q": query})
        response.raise_for_status()
        match = choose_result(response.json(), query, municipality)
        result = {"status": "ok" if match else "unresolved", "provider": "GSI", **(match or {})}
        self.cache[query] = result
        save_json(self.path, self.cache)
        return result
