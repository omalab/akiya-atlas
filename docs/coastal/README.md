# Coastal Kansai/Shikoku tracker (issue #1)

Purpose: find municipal vacant-house listings near the sea and an airport, with
optional purchase-price limits. The complete path is crawl → existing fact extraction
→ cached geography → offline site/data/feed build. This fork keeps the upstream MIT
license and attribution. It adds no photos, scraped descriptions, or private-platform
crawlers. Tracker titles are generated from municipality and listing number.

## Run

The engine is the same `hikuzawa/sitemill` tag used in CI, `v0.7.14`, installed as
the existing editable sibling dependency. From the parent directory:

```sh
git clone --depth 1 --branch v0.7.14 https://github.com/hikuzawa/sitemill.git sitemill
cd akiya-atlas
uv sync --frozen
git config core.hooksPath .githooks
uv run akiya-atlas coastal-enrich
uv run akiya-atlas coastal-build
uv run python -m http.server --bind 127.0.0.1 -d dist 8000
```

Open `/coastal/`. Maximum coast distance, estimated airport minutes and purchase
price in yen apply inclusively. Blank price means no price restriction; an explicit
price cap excludes unknown prices and rent-only listings, while zero-price sales
are eligible. The page paginates results, preserves conditions in its URL and can
download new-listing JSON/RSS for the current conditions. Permanent default feeds
use 5 km, 90 minutes and no price cap.

```sh
# Bounded enrichment (all eligible listings are attempted when no limit is supplied)
uv run akiya-atlas coastal-enrich --source mie-242152 --limit 20
# Export another set of conditions without rebuilding or accessing the network
uv run akiya-atlas coastal-export --max-coast-km 5 --max-airport-minutes 90 \
  --price-cap-yen 5000000 --out dist/coastal-budget
# Reproduce the bounded crawl in a disposable workspace; no HTML is committed
uv run python tools/coastal_sample.py --out /tmp/coastal-sample.json
```

Outputs:

| Path under `dist/` | Contents |
| --- | --- |
| `coastal/index.html` | Tracker and filter controls |
| `search/coastal.json` | All eligible target-region rows, computed fields, gaps and build time |
| `coastal/listings.json` | Rows matching the default export filters, with filter metadata |
| `coastal/new.json` | Matching rows first seen in the preceding 24 hours |
| `coastal/new.rss` | The same new rows as RSS 2.0 |

`coastal-build` wraps the original site build and exports feeds from its exact JSON
snapshot and timestamp. Plain upstream `sitemill build` generates the page and search
index, but does not export the feeds. Both fork workflows that build the site now use
`coastal-build`. The daily pipeline enriches first and commits `data/geo/` alongside
its other data. Deploy-only and Search Console rebuilds remain offline.

## Existing crawl, model and build

- `data/sources/*.yaml` defines each municipality, municipal operator evidence,
  host allowlist, page seeds and crawl/link-only policy. `service.crawls_listings`
  distinguishes actual listing crawls from subsidy-only crawls.
- `sitemill discover/crawl` uses `PoliteClient` for robots.txt, host delays,
  conditional requests and permitted hosts. The existing delay is 3 seconds plus
  jitter. State is in `data/state/crawl.json`; raw HTML is an ignored local cache.
  The sample uses this same engine with at most two pages per source and one worker.
- `sitemill extract` uses the existing LLM quote-then-parse schema for facts. Price,
  area and address are `FieldValue` objects with value, quote and parse status.
  `service.py` imports/merges records, preserves `first_seen_at`, and retires records
  when listing crawling stops. Records live in `data/records/<source>.jsonl`.
- `Dataset` joins municipal configuration and records. The tracker reuses active,
  nonduplicate records, actual listing-crawl policy and takedown exclusions.
  Existing optional source coordinates take priority over geocoding.
- `coastal-enrich` writes derived facts separately in `data/geo/listings.json`;
  it never overwrites extracted prices, addresses or first-seen dates. `pages.py`
  and Jinja templates supply the static UI and search JSON. The existing build
  checks trust signals, PII, imagery and URLs before completing.

## Geographic method and terms

Coordinates are always **longitude, latitude**, in degrees. All distance calculations
use the haversine sphere (mean Earth radius 6371.0088 km). Coast distance is the
minimum distance to each minor great-circle segment, including endpoints.

- **Geocoding:** the GSI Maps address-search endpoint. One sequential request per
  second at most; both positive and unmatched responses are persisted by normalized
  address in `data/geo/geocodes.json`. HTTP errors are retryable and are not stored
  as permanent misses. Exact normalized district-name matches are required;
  ambiguous matches and municipality-only centroids are rejected. The source
  addresses are already limited to districts by the upstream privacy policy. The
  returned points are district representatives, never proven building coordinates.
  This endpoint has no versioned API guarantee. Attribution is shown in the UI;
  see [GSI terms](https://maps.gsi.go.jp/help/termsofuse.html) and
  [GSI content terms](https://www.gsi.go.jp/kikakuchousei/kikakuchousei40182.html).
  Nominatim is not used.
- **Coast:** Natural Earth 1:10m coastline, with major islands, clipped to a generous
  Japanese regional bounding box (128–140°E, 29–38°N). The pinned upstream revision,
  original-download SHA-256 and public-domain license are embedded in
  `data/geo/coastline.json`. The source is generalized and omits small islands;
  borderline 5 km results require a detailed local map. It measures ocean coastline,
  **not beach availability, walking distance, safety, or legal access**.
  See [dataset notes](https://www.naturalearthdata.com/downloads/10m-physical-vectors/10m-coastline/)
  and [public-domain terms](https://www.naturalearthdata.com/about/terms-of-use/).
- **Airports:** all 83 Japanese airports marked with scheduled service and an IATA
  code in the pinned public-domain OurAirports snapshot, including all eleven
  candidates from the issue. Keeping the national set avoids missing closer airports
  such as Tajima or Tottori. `data/geo/airports.json` records coordinates, source
  revision/hash, scheduled-service flags and airport websites. This is a snapshot;
  verify actual passenger schedules with the airport before planning travel.
  See [source data and license](https://github.com/davidmegginson/ourairports-data).
- **Airport time:** choose the smallest great-circle airport distance; estimate
  `ceil(distance_km × 1.4 / 50 × 60 + 15)` minutes. This assumes a 1.4 road-distance
  multiplier, 50 km/h and 15 minutes of access time. No routing service is used.
  Water crossings, ferries, bridges, traffic and terrain are not modelled; island
  results can be especially optimistic. This limitation is prominent in the UI
  and feed metadata. It is not a guaranteed driving-time filter.

`tools/prepare_coastal_data.py` reproduces the redistributable reference subset.
Enrichment records carry the reference hashes and normalized address; the builder
marks stale enrichment pending when either changes. Builds make no geocoding calls.
Changing reference data requires running enrichment again.

First-seen windows use timezone-aware timestamps, include exactly 24 hours ago,
exclude future/invalid timestamps, and apply the same inclusive filter rules as
the search. Last-seen updates and price changes do not create new feed items.

## Coverage and observed results — 2026-10-21

The baseline already contained entries for all **322 municipalities** in the eleven
requested prefectures. Those entries do not imply all banks can be crawled. The
dated [coverage CSV](coverage-2026-10-21.csv) lists every municipality, operator
URL, bank URL, policy, listing-crawl status and observed record/geocoding counts.

One verified coastal gap was added: **Kuroshio, Kochi (`kochi-394289`)**. Its
[official municipal housing index](https://www.town.kuroshio.lg.jp/pb/cont/iju-sumu)
returned HTTP 200 through the robots-aware client. The municipal operator footer
was recorded as evidence. Existing subsidy seeds and other source policies remain.

| Prefecture | Municipal entries | Listing crawls | Active facts | Geocoded | 5 km / 90 min |
| --- | ---: | ---: | ---: | ---: | ---: |
| Osaka | 43 | 0 | 0 | 0 | 0 |
| Hyogo | 41 | 5 | 147 | 75 | 0 |
| Kyoto | 26 | 1 | 4 | 4 | 0 |
| Nara | 39 | 1 | 16 | 16 | 0 |
| Wakayama | 30 | 4 | 58 | 20 | 0 |
| Shiga | 19 | 2 | 20 | 5 | 0 |
| Mie | 29 | 7 | 68 | 65 | 5 |
| Kochi | 34 | 15 | 257 | 200 | 64 |
| Ehime | 20 | 2 | 2 | 1 | 0 |
| Tokushima | 24 | 5 | 53 | 36 | 2 |
| Kagawa | 17 | 0 | 0 | 0 | 0 |
| Total | 322 | 42 | 625 | 422 | 71 |

All 625 currently eligible inherited listings were attempted: **422 resolved, 179
unmatched, 24 without a usable address**. There were 294 unique GSI requests. A
second enrichment run made zero GSI requests. At 5 km / 90 minutes, 71 match with
no purchase-price restriction; **27** match with a **¥5,000,000** purchase-price cap.

The [bounded live crawl report](sample-2026-10-21.json) covers Yura, Shima, Kuroshio
and Aki: **7 pages fetched**, **1 HTTP 502** (Shima listing endpoint), **13 HTTP
requests including robots and retry**, one worker, at most two pages per source.
Those municipalities have **126 inherited active records**, **62** of which pass
5 km / 90 minutes. These are inherited record counts, not newly extracted records
from the live crawl. No municipal raw HTML is committed.

Blocked or intentionally omitted:

- Fresh LLM extraction needs `ANTHROPIC_API_KEY` in this repository's `.env`.
  The sample recorded the missing-key failure and imported **zero** new records.
  Re-run the sample or the normal extraction pipeline after configuring it.
- Shima's listing endpoint returned HTTP 502 on the bounded sample; it was not
  bypassed. The existing records were retained. Retry through the normal crawler.
- The 203 unresolved/addressless listings stay out of distance-filtered results
  and feeds. Their status remains visible in the data and UI; no location is invented.
- Link-only, third-party, registration-only and unsupported sources retain their
  upstream boundaries. In particular there are currently no listing crawls in
  Osaka or Kagawa; municipal entries there are coverage of bank links, not inventory.
- The optional MLIT reinfolib enrichment was not enabled. There are no API calls,
  sale-price comparisons, zoning claims or hazard classifications from it.
- The inherited records have no first-seen timestamps in the sample's last 24 hours,
  so the real new feeds are empty. Synthetic boundary fixtures verify positive cases.
- No deployment was performed. Before hosting this fork, set its own domain and
  operator/contact configuration; the inherited site configuration names the upstream
  deployment. The PR does not claim control of that domain.

## Verification

The upstream baseline had 309 passing Python tests and 6 private-HTML skips.
The candidate adds geometry, GSI caching/rate-limit, stale provenance, filter,
first-seen-window, JSON/RSS parity and browser-rule tests. The two upstream exact
artifact-count assertions now account for the added tracker page and JSON file.
Existing ordinary search and listing behavior stays covered by the same suite.

```sh
uv run pytest
uv run ruff check src tests tools/prepare_coastal_data.py tools/coastal_sample.py
node --test tests/coastal_ui.test.cjs
uv run akiya-atlas coastal-build
uv run akiya-atlas ad-check
uv run akiya-atlas publish-check
```

The full build generates 6,973 HTML pages. Browser proof checks the default results,
coast/airport/price changes and zero-result state; screenshots are saved beside this
report. Geographic estimates, visual presentation and regression tests are separate
proof obligations; passing tests do not make the estimates exact.

Observed candidate results: **318 Python tests passed, 6 skipped** (private HTML
fixtures unavailable); **3 Node tests passed**; Ruff, advertising checks and publish
checks passed. The browser returned **71** default results, **14** at 1 km / 60 min /
¥5,000,000, and **0** at 0 km / 0 min. The exported data gives the same counts.
Screenshots: [default](screenshots/default.png), [filtered](screenshots/filtered.png),
[empty](screenshots/empty.png). The local macOS Python installation skips editable
`.pth` files when this host marks them hidden; local verification used
`PYTHONPATH=src:../sitemill/src` with the commands above. CI uses normal editable
installation without that host-specific workaround.
