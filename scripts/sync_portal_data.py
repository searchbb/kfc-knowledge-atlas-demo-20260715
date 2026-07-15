#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path


SITE_ROOT = Path(__file__).resolve().parents[1]
BUILD_SCRIPT = Path(__file__).resolve().with_name("build_site_data.py")


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def find_repo_root() -> Path:
    for candidate in Path(__file__).resolve().parents:
        if (candidate / "data/semantic_pipeline_v2").exists() and (
            candidate / "data/news_library/news_library.sqlite3"
        ).exists():
            return candidate
    raise SystemExit("Could not infer KFC repo root. Pass --repo-root explicitly.")


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def run_build(*, repo_root: Path, out_path: Path) -> None:
    command = [
        sys.executable,
        str(BUILD_SCRIPT),
        "--repo-root",
        str(repo_root),
        "--out",
        str(out_path),
    ]
    subprocess.run(command, check=True)


def summarize_payload(path: Path) -> dict[str, object]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    collections = payload.get("collections", {})
    counts = {
        name: len(rows) for name, rows in collections.items() if isinstance(rows, list)
    }
    return {
        "schema_version": payload.get("schemaVersion", ""),
        "counts": counts,
        "relation_count": len(payload.get("relations", [])),
        "timeline_count": len(payload.get("timeline", [])),
    }


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Rebuild portal site-data.json from local KFC truth sources."
    )
    parser.add_argument("--repo-root", default=str(find_repo_root()))
    parser.add_argument("--out", default=str(SITE_ROOT / "data" / "site-data.json"))
    args = parser.parse_args()

    repo_root = Path(args.repo_root).expanduser().resolve()
    out_path = Path(args.out).expanduser().resolve()
    out_path.parent.mkdir(parents=True, exist_ok=True)

    before_exists = out_path.exists()
    before_sha = sha256_file(out_path) if before_exists else ""

    with tempfile.NamedTemporaryFile(
        prefix="site-data-", suffix=".json", dir=str(out_path.parent), delete=False
    ) as handle:
        temp_path = Path(handle.name)

    try:
        run_build(repo_root=repo_root, out_path=temp_path)
        after_sha = sha256_file(temp_path)
        summary = summarize_payload(temp_path)
        temp_path.replace(out_path)
    finally:
        if temp_path.exists():
            temp_path.unlink()

    result = {
        "status": "success",
        "generated_at": now_iso(),
        "repo_root": str(repo_root),
        "out": str(out_path),
        "replaced_existing": before_exists,
        "changed": before_sha != after_sha,
        "before_sha256": before_sha,
        "after_sha256": after_sha,
        **summary,
    }
    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
