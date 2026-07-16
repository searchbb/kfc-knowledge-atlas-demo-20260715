#!/usr/bin/env python3
from __future__ import annotations

import argparse
import gzip
import json
from pathlib import Path


SITE_ROOT = Path(__file__).resolve().parents[1]
FORBIDDEN_ITEM_FIELDS = {"html", "text", "path", "url"}
SUMMARY_LIMITS = {"articles": 0, "news": 240, "research": 600, "issues": 600, "cards": 600, "topics": 600}


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate the lightweight portal index projection.")
    parser.add_argument("--site-data", default=str(SITE_ROOT / "data" / "site-data.json"))
    parser.add_argument("--site-index", default=str(SITE_ROOT / "data" / "site-index.json"))
    parser.add_argument("--max-bytes", type=int, default=1_500_000)
    parser.add_argument("--max-gzip-bytes", type=int, default=500_000)
    args = parser.parse_args()

    full_path = Path(args.site_data).resolve()
    index_path = Path(args.site_index).resolve()
    raw = index_path.read_bytes()
    compressed = gzip.compress(raw, compresslevel=9, mtime=0)
    full = json.loads(full_path.read_text(encoding="utf-8"))
    index = json.loads(raw)
    errors: list[str] = []

    if len(raw) > args.max_bytes:
        errors.append(f"site-index raw bytes exceed limit: {len(raw)} > {args.max_bytes}")
    if len(compressed) > args.max_gzip_bytes:
        errors.append(
            f"site-index gzip bytes exceed limit: {len(compressed)} > {args.max_gzip_bytes}"
        )

    full_collections = dict(full.get("collections") or {})
    index_collections = dict(index.get("collections") or {})
    counts: dict[str, int] = {}
    for name, full_rows in full_collections.items():
        index_rows = list(index_collections.get(name) or [])
        counts[name] = len(index_rows)
        if len(index_rows) != len(list(full_rows or [])):
            errors.append(f"collection count mismatch for {name}: {len(index_rows)} != {len(full_rows)}")
        summary_limit = SUMMARY_LIMITS.get(name, 600)
        for position, item in enumerate(index_rows):
            forbidden = sorted(FORBIDDEN_ITEM_FIELDS.intersection(item))
            if forbidden:
                errors.append(f"{name}[{position}] contains detail-only fields: {forbidden}")
            summary = item.get("summary")
            if summary_limit <= 0 and summary:
                errors.append(f"{name}[{position}] unexpectedly contains a summary")
            if isinstance(summary, str) and len(summary) > summary_limit:
                errors.append(
                    f"{name}[{position}] summary exceeds {summary_limit} characters: {len(summary)}"
                )

    if len(index.get("relations") or []) != len(full.get("relations") or []):
        errors.append("relation count mismatch")
    if len(index.get("timeline") or []) != len(full.get("timeline") or []):
        errors.append("timeline count mismatch")
    if dict(index.get("stats") or {}) != dict(full.get("stats") or {}):
        errors.append("stats projection mismatch")

    app_source = (SITE_ROOT / "app.js").read_text(encoding="utf-8")
    if "site-data.json" in app_source:
        errors.append("app.js still references site-data.json")
    if "site-index.json" not in app_source:
        errors.append("app.js does not reference site-index.json")

    result = {
        "status": "passed" if not errors else "failed",
        "site_data": str(full_path),
        "site_index": str(index_path),
        "raw_bytes": len(raw),
        "gzip_bytes": len(compressed),
        "raw_limit": args.max_bytes,
        "gzip_limit": args.max_gzip_bytes,
        "counts": counts,
        "relation_count": len(index.get("relations") or []),
        "timeline_count": len(index.get("timeline") or []),
        "errors": errors,
    }
    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
    return 0 if not errors else 1


if __name__ == "__main__":
    raise SystemExit(main())
