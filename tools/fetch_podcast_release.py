"""Fetch one complete, validated publication snapshot for a Pages build."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import re
import shutil
import subprocess
import tempfile

from podcast_publication import validate_bundle, validate_catalog


def gh(*args: str) -> str:
    return subprocess.run(["gh", *args], capture_output=True, text=True, check=True, timeout=180).stdout


def fetch_release(repository: str, output: Path, tag: str | None) -> dict:
    if not re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", repository):
        raise ValueError("Invalid repository")
    if not tag:
        releases = json.loads(gh("release", "list", "--repo", repository, "--limit", "100",
                                "--json", "tagName,createdAt,isDraft,isPrerelease"))
        eligible = [row for row in releases if not row["isDraft"] and not row["isPrerelease"]
                    and re.fullmatch(r"podcast-audio-\d{8}T\d{6}Z", row["tagName"])]
        if not eligible:
            raise ValueError("No published podcast audio snapshot")
        tag = max(eligible, key=lambda row: row["createdAt"])["tagName"]
    if not re.fullmatch(r"podcast-audio-\d{8}T\d{6}Z", tag):
        raise ValueError("Invalid podcast release tag")
    with tempfile.TemporaryDirectory(prefix="podcast-release-") as temporary:
        bundle = Path(temporary)
        gh("release", "download", tag, "--repo", repository, "--pattern", "episodes.json", "--dir", str(bundle))
        catalog = validate_catalog(json.loads((bundle / "episodes.json").read_text(encoding="utf-8")))
        (bundle / "media").mkdir()
        for asset in sorted({Path(episode["audio"]).name for episode in catalog["episodes"]}):
            gh("release", "download", tag, "--repo", repository, "--pattern", asset, "--dir", str(bundle / "media"))
        summary = validate_bundle(bundle)
        if (output / "media").exists():
            raise ValueError("Build output already contains media; use a clean frontend build")
        shutil.copytree(bundle / "media", output / "media")
        shutil.copyfile(bundle / "episodes.json", output / "episodes.json")
    return {**summary, "release": tag}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repository", required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--tag")
    args = parser.parse_args()
    print(json.dumps(fetch_release(args.repository, args.output, args.tag)))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
