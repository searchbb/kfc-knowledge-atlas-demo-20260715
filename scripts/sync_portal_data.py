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

from validate_portal_data import validate_portal_file


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
        "build_id": dict(payload.get("buildMeta") or {}).get("buildId", ""),
        "source_digest": dict(payload.get("buildMeta") or {}).get("sourceDigest", ""),
    }


def validate_count_changes(*, before_path: Path, after_path: Path, max_drop_ratio: float) -> None:
    if not before_path.exists():
        return
    before = summarize_payload(before_path).get("counts", {})
    after = summarize_payload(after_path).get("counts", {})
    for name, old_value in dict(before).items():
        new_value = int(dict(after).get(name, 0))
        old_value = int(old_value)
        if old_value <= 0:
            continue
        drop_ratio = (old_value - new_value) / old_value
        if drop_ratio > max_drop_ratio:
            raise RuntimeError(
                f"count drop guard rejected {name}: {old_value} -> {new_value} "
                f"({drop_ratio:.1%} > {max_drop_ratio:.1%})"
            )


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Rebuild portal site-data.json from local KFC truth sources."
    )
    parser.add_argument("--repo-root", default="")
    parser.add_argument("--out", default=str(SITE_ROOT / "data" / "site-data.json"))
    parser.add_argument("--max-count-drop-ratio", type=float, default=0.05)
    parser.add_argument("--allow-count-drop", action="store_true")
    args = parser.parse_args()

    repo_root = Path(args.repo_root or str(find_repo_root())).expanduser().resolve()
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
        validation = validate_portal_file(temp_path)
        after_sha = sha256_file(temp_path)
        summary = summarize_payload(temp_path)
        if not args.allow_count_drop:
            validate_count_changes(
                before_path=out_path,
                after_path=temp_path,
                max_drop_ratio=max(0.0, args.max_count_drop_ratio),
            )
        before_summary = summarize_payload(out_path) if before_exists else {}
        source_unchanged = bool(before_exists) and (
            before_summary.get("source_digest") == summary.get("source_digest")
        )
        if source_unchanged:
            after_sha = before_sha
        else:
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
        "source_unchanged": source_unchanged,
        "before_sha256": before_sha,
        "after_sha256": after_sha,
        **summary,
        "validation": validation,
    }
    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
