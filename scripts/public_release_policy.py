"""Fail-closed publication policy for the static public portal."""

from __future__ import annotations

import json
import re
from collections import Counter
from typing import Iterable


DENIED_RESEARCH_SOURCE_PREFIXES = ("research/department_strategy/",)
STRICT_VISIBLE_MARKERS = (
    "会议纪要",
    "会议记录",
    "内部会议",
    "内部讨论",
    "内部材料",
    "内部资料",
    "内部研究",
    "未公开资料",
    "未公开信息",
    "用户上传",
    "用户提供的资料",
    "你提供的资料",
    "您提供的资料",
    "上传材料",
    "上传资料",
    "据内部",
    "我司内部",
    "PRIVATE_ROUTING_ONLY_DO_NOT_PUBLISH",
    "meeting minutes",
    "internal meeting",
    "user-uploaded material",
    "confidential material",
)
CORPORATE_EMAIL_RE = re.compile(
    r"[A-Za-z0-9._%+-]+@(?:huawei|h-partners)\.com", re.IGNORECASE
)


def publication_violations(collection: str, item: dict) -> list[str]:
    """Return reason codes only, so audits never echo private copy."""
    violations: list[str] = []
    source_path = str(item.get("path") or "").replace("\\", "/")
    if collection == "research" and source_path.startswith(DENIED_RESEARCH_SOURCE_PREFIXES):
        violations.append("private_research_source_class")
    if collection == "articles" and not str(item.get("url") or "").startswith(("http://", "https://")):
        violations.append("article_missing_public_source_url")
    serialized = json.dumps(item, ensure_ascii=False)
    if collection in {"issues", "cards", "research", "articles"}:
        lowered = serialized.lower()
        for index, marker in enumerate(STRICT_VISIBLE_MARKERS, start=1):
            if marker.lower() in lowered:
                violations.append(f"forbidden_provenance_term_{index}")
    if CORPORATE_EMAIL_RE.search(serialized):
        violations.append("corporate_email_address")
    return sorted(set(violations))


def partition_public_items(collection: str, items: Iterable[dict]) -> tuple[list[dict], dict]:
    accepted: list[dict] = []
    reasons: Counter[str] = Counter()
    excluded = 0
    for item in items:
        violations = publication_violations(collection, item)
        if violations:
            excluded += 1
            reasons.update(violations)
        else:
            accepted.append(item)
    return accepted, {
        "excluded": excluded,
        "reasonCounts": dict(sorted(reasons.items())),
    }
