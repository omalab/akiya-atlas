"""Reproducible bounded live crawl; raw HTML lives only in a temporary workspace.

uv run python tools/coastal_sample.py --out docs/coastal/sample-2026-10-21.json
The geographical counts use inherited records, separately from the live crawl.
"""

from __future__ import annotations

import argparse
import json
import shutil
import tempfile
from dataclasses import replace
from pathlib import Path

import yaml
from sitemill import commands
from sitemill.diff.state import CrawlState
from sitemill.models import utcnow
from sitemill.settings import SecretsError, Workspace

from akiya_atlas.coastal import Filters, matches, tracker_rows
from akiya_atlas.data import Dataset
from akiya_atlas.geocode import save_json
from akiya_atlas.service import service

ROOT = Path(__file__).resolve().parents[1]
SOURCES = ["wakayama-303836", "mie-242152", "kochi-394289", "kochi-392031"]


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    ws = Workspace.open(ROOT)
    entries = [
        s
        for path in sorted(ws.sources_dir.glob("*.yaml"))
        for s in yaml.safe_load(path.read_text())["sources"]
        if s["id"] in SOURCES
    ]
    with tempfile.TemporaryDirectory(prefix="akiya-coastal-crawl-") as temp:
        root = Path(temp)
        shutil.copy(ROOT / "site.toml", root / "site.toml")
        directory = root / "data" / "sources"
        directory.mkdir(parents=True)
        (directory / "sample.yaml").write_text(yaml.safe_dump({"sources": entries}))
        rt = commands.Runtime.open(root, service=service)
        rt.ws = replace(rt.ws, secrets=ws.secrets)
        rt.ws.ensure_dirs()
        crawl = commands.cmd_crawl(rt, SOURCES, max_pages=2, force=True, workers=1)
        state = CrawlState.load(rt.state_path)
        extract: dict
        try:
            report = commands.cmd_extract(rt, SOURCES, limit=2, workers=1)
            extract = report.model_dump(mode="json")
        except SecretsError as error:
            extract = {"blocked": str(error), "new_records": 0}
        pages = [
            {
                "source_id": p.source_id,
                "url": p.url,
                "kind": p.kind,
                "status": p.status,
                "error": p.error,
            }
            for p in state.urls.values()
        ]
    inherited = tracker_rows(ws, Dataset.load(ws))
    sample = [
        r
        for r in inherited
        if r["id"] and any(r["muni_code"] == entry["municipality"]["code"] for entry in entries)
    ]
    result = {
        "run_at": utcnow().isoformat(),
        "source_ids": SOURCES,
        "max_pages_per_source": 2,
        "crawl": crawl.model_dump(mode="json"),
        "pages": pages,
        "extract": extract,
        "inherited_active_sample_records": len(sample),
        "inherited_sample_within_5km_90min": sum(matches(r, Filters()) for r in sample),
        "all_inherited_active_records": len(inherited),
        "all_inherited_within_5km_90min": sum(matches(r, Filters()) for r in inherited),
        "count_basis": "Inherited fact records; not newly extracted listings from this crawl.",
    }
    save_json(args.out, result)
    print(
        json.dumps(
            {k: v for k, v in result.items() if k not in ("pages", "crawl", "extract")},
            ensure_ascii=False,
        )
    )


if __name__ == "__main__":
    main()
