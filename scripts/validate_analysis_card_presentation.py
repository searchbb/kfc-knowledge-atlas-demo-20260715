#!/usr/bin/env python3
"""Validate that public analysis-card control labels are Chinese."""

from __future__ import annotations

import json
import re
from html import unescape
from pathlib import Path


SITE_ROOT = Path(__file__).resolve().parents[1]
SITE_DATA = SITE_ROOT / "data/site-data.json"
ENGLISH_CONTROL_PREFIXES = (
    "Issue Card",
    "Evidence Capsule",
    "Incomplete Issue Card Capsule",
    "Metadata",
    "Canonical Question",
    "Why It Matters",
    "Current Viewpoints",
    "Viewpoint",
    "Key Evidence",
    "Mechanisms",
    "Risks / Uncertainties",
    "Related Articles",
    "Archived / Replaced",
    "Retire Record",
    "Former Canonical Question",
    "Why This Was Migrated",
    "Supporting Evidence",
    "Governance Note",
    "Deferred Recovery Rule",
)


def tag_texts(body: str, tag: str) -> list[str]:
    return [
        re.sub(r"\s+", " ", unescape(re.sub(r"<[^>]+>", " ", value))).strip()
        for value in re.findall(fr"<{tag}[^>]*>(.*?)</{tag}>", body, re.IGNORECASE | re.DOTALL)
    ]


def main() -> int:
    payload = json.loads(SITE_DATA.read_text(encoding="utf-8"))
    collections = payload["collections"]
    rows = list(collections["issues"]) + list(collections["cards"])
    violations: list[dict[str, str]] = []
    for item in rows:
        headings = sum((tag_texts(item["html"], tag) for tag in ("h1", "h2", "h3", "h4")), [])
        for heading in headings:
            if any(heading.lower().startswith(prefix.lower()) for prefix in ENGLISH_CONTROL_PREFIXES):
                violations.append({"id": item["id"], "heading": heading})
    representative = next(item for item in collections["issues"] if item.get("status") == "active")
    for required in ("分析卡片", "基本信息", "核心问题", "当前观点", "关键证据", "作用机制", "风险与不确定性", "相关文章"):
        if required not in representative["html"]:
            violations.append({"id": representative["id"], "heading": f"missing:{required}"})
    result = {
        "status": "passed" if not violations else "failed",
        "checked_cards": len(rows),
        "violations": violations,
    }
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if not violations else 1


if __name__ == "__main__":
    raise SystemExit(main())
