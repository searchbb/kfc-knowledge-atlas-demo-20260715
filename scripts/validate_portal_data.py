#!/usr/bin/env python3
"""Validate portal counts, required fields, relations, timelines, and public safety."""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path

from portal_schema import validate_portal_payload


ABSOLUTE_PATH = re.compile(r"(?:/Users/|[A-Za-z]:\\\\)")


def validate_portal_file(path: Path) -> dict[str, object]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    validate_portal_payload(payload)
    collections = dict(payload["collections"])
    errors: list[str] = []
    indexes: dict[str, set[str]] = {}
    for name, rows in collections.items():
        entity_type = {"topics": "topic", "issues": "issue", "cards": "card", "research": "research", "articles": "article", "news": "news"}[name]
        ids = [str(row.get("id") or "") for row in rows]
        if "" in ids:
            errors.append(f"{name} contains empty id")
        if len(ids) != len(set(ids)):
            errors.append(f"{name} contains duplicate ids")
        indexes[entity_type] = set(ids)
        expected = int(dict(payload.get("stats") or {}).get(name, -1))
        if name == "news":
            news_meta = dict(payload.get("newsMeta") or {})
            if expected != int(news_meta.get("totalCount", -1)):
                errors.append("stats.news must equal newsMeta.totalCount")
            if len(rows) != int(news_meta.get("mirroredCount", -1)):
                errors.append("collections.news must equal newsMeta.mirroredCount")
            if len(rows) > int(news_meta.get("windowLimit", 0)):
                errors.append("collections.news exceeds bounded window")
        elif expected != len(rows):
            errors.append(f"stats.{name}={expected} but collection has {len(rows)}")

    orphan_relations = []
    for relation in payload.get("relations", []):
        if relation["fromId"] not in indexes.get(relation["fromType"], set()) or relation["toId"] not in indexes.get(relation["toType"], set()):
            orphan_relations.append(relation["id"])
    if orphan_relations:
        errors.append(f"orphan relations: {', '.join(orphan_relations[:10])}")

    orphan_timeline = []
    for item in payload.get("timeline", []):
        if item["id"] not in indexes.get(item["type"], set()):
            orphan_timeline.append(f"{item['type']}:{item['id']}")
    if orphan_timeline:
        errors.append(f"orphan timeline rows: {', '.join(orphan_timeline[:10])}")

    serialized = json.dumps(payload, ensure_ascii=False)
    if ABSOLUTE_PATH.search(serialized):
        errors.append("public payload contains an absolute workstation path")
    build_meta = dict(payload.get("buildMeta") or {})
    for field in ("buildId", "sourceDigest", "sourceRevision", "generatorVersion"):
        if not build_meta.get(field):
            errors.append(f"buildMeta.{field} is required")
    if errors:
        raise ValueError("; ".join(errors))
    return {
        "status": "passed",
        "path": str(path),
        "counts": {name: len(rows) for name, rows in collections.items()},
        "relation_count": len(payload.get("relations", [])),
        "timeline_count": len(payload.get("timeline", [])),
        "news_total_count": dict(payload.get("newsMeta") or {}).get("totalCount", 0),
        "news_mirrored_count": dict(payload.get("newsMeta") or {}).get("mirroredCount", 0),
        "build_id": build_meta.get("buildId"),
        "absolute_path_leaks": 0,
        "orphan_relations": 0,
        "orphan_timeline_rows": 0,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("path", nargs="?", default=str(Path(__file__).resolve().parents[1] / "data/site-data.json"))
    args = parser.parse_args()
    try:
        result = validate_portal_file(Path(args.path).expanduser().resolve())
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        print(json.dumps({"status": "failed", "error": str(exc)}, ensure_ascii=False, indent=2))
        return 1
    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
