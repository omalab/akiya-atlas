"""Prove the source-ID exception is limited to its exact file and value shape."""

from __future__ import annotations

import json
import subprocess
import sys
import tempfile
from pathlib import Path


def main() -> None:
    binary = str(Path(sys.argv[1]).resolve())
    config = Path(__file__).resolve().parents[2] / ".gitleaks.toml"
    with tempfile.TemporaryDirectory(prefix="gitleaks-config-proof-") as temp:
        root = Path(temp)
        log = root / "data/runs/operator-rechecks.jsonl"
        log.parent.mkdir(parents=True)
        # Manufactured fixture, not a working credential. Construct at runtime so
        # the fixture source itself is not an apparent key assignment.
        sentinel = "a7Qm9VzR2p8Yn4Ks" + "6Wc3Jd5Hx0Lf1TbE"
        public_source = "tokushima-363880"
        log.write_text(
            json.dumps({"key": public_source}) + "\n" + json.dumps({"key": sentinel}) + "\n"
        )
        (root / "other.jsonl").write_text(json.dumps({"key": public_source}) + "\n")
        for args in (
            ["init", "--quiet"],
            ["add", "."],
            [
                "-c",
                "user.name=Scan fixture",
                "-c",
                "user.email=fixture@example.invalid",
                "commit",
                "--no-gpg-sign",
                "--quiet",
                "-m",
                "Synthetic scan fixture",
            ],
        ):
            subprocess.run(["git", "-C", str(root), *args], check=True, capture_output=True)
        report = root / "result.json"
        result = subprocess.run(
            [
                binary,
                "git",
                str(root),
                "--config",
                str(config),
                "--redact",
                "--no-banner",
                "--report-format",
                "json",
                "--report-path",
                str(report),
            ],
            capture_output=True,
        )
        if result.returncode != 1 or not report.exists():
            raise AssertionError("synthetic key was not detected or scanner failed")
        findings = json.loads(report.read_text())
        actual = {(r["File"], r["StartLine"]) for r in findings}
        expected = {("data/runs/operator-rechecks.jsonl", 2), ("other.jsonl", 1)}
        if actual != expected or len(findings) != 2:
            raise AssertionError(f"unexpected redacted finding locations: {sorted(actual)}")
    print("Gitleaks config proof passed: only municipal source IDs in the exact log are exempt")


if __name__ == "__main__":
    main()
