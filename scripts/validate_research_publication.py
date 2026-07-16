#!/usr/bin/env python3
"""Validate the curated research publication set and its static media."""

from __future__ import annotations

import json
import re
from datetime import datetime
from pathlib import Path

from research_publication import SHA256_RE, VERIFIED_ADMISSION, public_content_violation


SITE_ROOT = Path(__file__).resolve().parents[1]
MANIFEST = Path(__file__).resolve().with_name("research_publication_manifest.json")
DATA = SITE_ROOT / "data" / "site-data.json"
IMAGE_SRC_RE = re.compile(r'<img[^>]+src="(?P<src>[^"]+)"', re.IGNORECASE)
EXCLUDED_MARKERS = (
    "prompt",
    "draft",
    "evidence_ledger",
    "review",
    "audit",
    "checklist",
    "source_notes",
    "gpt_call",
)


def main() -> int:
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    payload = json.loads(DATA.read_text(encoding="utf-8"))
    reports = list(payload["collections"]["research"])
    manifest_rows = list(manifest["reports"])
    expected_count = len(manifest_rows)
    assert expected_count > 0
    assert len({row["id"] for row in manifest_rows}) == expected_count
    assert len({row["path"] for row in manifest_rows}) == expected_count
    assert {row["id"] for row in reports}.issubset({row["id"] for row in manifest_rows})
    audit = dict(dict(payload.get("buildMeta") or {}).get("publicationAudit") or {})
    excluded = int(dict(audit.get("research") or {}).get("excluded") or 0)
    assert len(reports) + excluded == expected_count, (len(reports), excluded, expected_count)
    report_by_id = {str(row["id"]): row for row in reports}
    verified_count = 0
    for row in manifest_rows:
        lowered = Path(row["path"]).name.lower()
        assert not any(marker in lowered for marker in EXCLUDED_MARKERS), row["path"]
        if row.get("admission") != VERIFIED_ADMISSION:
            continue
        verified_count += 1
        assert str(row["id"]) in report_by_id, row
        assert SHA256_RE.fullmatch(str(row.get("sha256") or "")), row
        published_at = str(row.get("published_at") or "")
        parsed = datetime.fromisoformat(published_at.replace("Z", "+00:00"))
        assert parsed.tzinfo is not None, row
        projected = report_by_id[str(row["id"])]
        assert projected.get("updatedAt") == published_at, (projected, row)
        assert projected.get("status") == "published", projected
        violation = public_content_violation(
            "\n".join(
                str(projected.get(field) or "")
                for field in ("html", "text", "summary", "canonicalQuestion")
            )
        )
        assert not violation, (row["id"], violation)
    diagram_count = sum(int(row.get("diagramCount") or 0) for row in reports)
    local_images: list[str] = []
    missing_images: list[str] = []
    for report in reports:
        for match in IMAGE_SRC_RE.finditer(str(report.get("html") or "")):
            source = match.group("src")
            if source.startswith(("http://", "https://", "data:")):
                continue
            local_images.append(source)
            path = SITE_ROOT / source.removeprefix("./")
            if not path.is_file():
                missing_images.append(source)
    assert not missing_images, missing_images
    asset_files = sorted((SITE_ROOT / "assets" / "research").rglob("*.png"))
    referenced_asset_paths = {
        str((SITE_ROOT / source.removeprefix("./")).resolve())
        for source in local_images
        if source.removeprefix("./").startswith("assets/research/")
    }
    assert referenced_asset_paths.issubset({str(path.resolve()) for path in asset_files})
    result = {
        "status": "passed",
        "research_count": len(reports),
        "diagram_count": diagram_count,
        "local_image_count": len(local_images),
        "staged_png_count": len(asset_files),
        "missing_image_count": 0,
        "process_artifacts_published": 0,
        "verified_admission_count": verified_count,
    }
    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
