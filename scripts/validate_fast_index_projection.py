#!/usr/bin/env python3
from __future__ import annotations

import argparse
import gzip
import html
import json
import re
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

    route_home_path = SITE_ROOT / "data" / "route-home.json"
    route_home = json.loads(route_home_path.read_text(encoding="utf-8"))
    index_html_path = SITE_ROOT / "index.html"
    index_html = index_html_path.read_text(encoding="utf-8")
    bootstrap_match = re.search(
        r'data-home-bootstrap data-generated-at="([^"]+)"', index_html
    )
    bootstrap_generated_at = html.unescape(bootstrap_match.group(1)) if bootstrap_match else ""
    if not bootstrap_generated_at:
        errors.append("index.html is missing the static home bootstrap version")
    if bootstrap_generated_at != str(route_home.get("generatedAt") or ""):
        errors.append("static home bootstrap and route-home generatedAt differ")
    home_news = list(dict(route_home.get("collections") or {}).get("news") or [])
    latest_news = sorted(
        home_news,
        key=lambda item: str(item.get("publishedAt") or item.get("updatedAt") or ""),
        reverse=True,
    )
    if latest_news and html.escape(str(latest_news[0].get("title") or "")) not in index_html:
        errors.append("static home bootstrap does not contain the latest home headline")
    index_html_gzip_bytes = len(
        gzip.compress(index_html_path.read_bytes(), compresslevel=9, mtime=0)
    )
    if index_html_gzip_bytes > 30_000:
        errors.append(f"index.html bootstrap gzip bytes exceed limit: {index_html_gzip_bytes}")

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
        "bootstrap_generated_at": bootstrap_generated_at,
        "route_home_generated_at": route_home.get("generatedAt"),
        "index_html_gzip_bytes": index_html_gzip_bytes,
        "errors": errors,
    }
    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
    return 0 if not errors else 1


if __name__ == "__main__":
    raise SystemExit(main())
