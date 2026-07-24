from __future__ import annotations

from typing import Any


PORTAL_SCHEMA_VERSION = "kfc_portal_schema_v1"

COLLECTION_FIELDS = {
    "topics": [
        "id",
        "title",
        "status",
        "issueCountDeclared",
        "articleCount",
        "lastUpdated",
        "issueIds",
        "activeIssueIds",
        "relatedCardIds",
        "relatedResearchIds",
    ],
    "issues": [
        "id",
        "type",
        "title",
        "topicId",
        "status",
        "sourceArticleCount",
        "updatedAt",
        "createdAt",
        "canonicalQuestion",
        "path",
        "mtime",
        "html",
        "text",
    ],
    "cards": [
        "id",
        "type",
        "title",
        "topicId",
        "status",
        "sourceArticleCount",
        "updatedAt",
        "createdAt",
        "canonicalQuestion",
        "path",
        "mtime",
        "html",
        "text",
    ],
    "research": [
        "id",
        "type",
        "title",
        "topicId",
        "status",
        "updatedAt",
        "createdAt",
        "canonicalQuestion",
        "path",
        "mtime",
        "html",
        "text",
    ],
    "articles": [
        "id",
        "type",
        "title",
        "sourceId",
        "status",
        "publishedAt",
        "updatedAt",
        "summary",
        "path",
        "url",
    ],
    "news": [
        "id",
        "type",
        "title",
        "sourceId",
        "status",
        "publishedAt",
        "updatedAt",
        "summary",
        "articleId",
        "url",
    ],
    "objects": [
        "id",
        "type",
        "title",
        "status",
        "category",
        "summary",
        "updatedAt",
        "createdAt",
        "objectType",
        "businessArchetype",
        "attentionLevel",
        "strategicPosition",
        "strategicThesis",
        "updates",
        "facts",
        "metrics",
        "metricSummary",
        "trends",
        "thesis",
        "competitiveRelationships",
        "longTermSections",
        "recentUpdates",
        "recentWindowDays",
        "alerts7d",
        "factCount",
        "longTermUpdatedAt",
        "evidenceCoverage",
        "html",
    ],
    "signals": [
        "id",
        "type",
        "title",
        "status",
        "summary",
        "updatedAt",
        "createdAt",
        "hypothesisId",
        "deltaDirection",
        "priorView",
        "newEvidence",
        "updatedView",
        "counterevidenceOrLimit",
        "followUpQuestion",
        "confidence",
        "sourceGrade",
        "sourceId",
        "url",
        "sourceArticleIds",
        "evidenceRefs",
        "reviewReason",
        "signalDate",
        "html",
    ],
}

RELATION_FIELDS = ["id", "type", "fromType", "fromId", "toType", "toId"]
TIMELINE_FIELDS = [
    "id",
    "type",
    "title",
    "topicId",
    "updatedAt",
    "path",
    "eventType",
    "eventLabel",
    "sourceStatus",
]


def schema_descriptor() -> dict[str, Any]:
    return {
        "schemaVersion": PORTAL_SCHEMA_VERSION,
        "entityCollections": COLLECTION_FIELDS,
        "relations": RELATION_FIELDS,
        "timeline": TIMELINE_FIELDS,
    }


def _require_fields(rows: list[dict[str, Any]], required_fields: list[str], label: str) -> None:
    for index, row in enumerate(rows):
        if not isinstance(row, dict):
            raise ValueError(f"{label}[{index}] must be an object")
        missing = [field for field in required_fields if field not in row]
        if missing:
            raise ValueError(f"{label}[{index}] missing fields: {', '.join(missing)}")


def validate_portal_payload(payload: dict[str, Any]) -> None:
    if payload.get("schemaVersion") != PORTAL_SCHEMA_VERSION:
        raise ValueError("schemaVersion does not match the active portal schema")
    collections = payload.get("collections")
    if not isinstance(collections, dict):
        raise ValueError("collections must be an object")

    for name, required_fields in COLLECTION_FIELDS.items():
        rows = collections.get(name)
        if not isinstance(rows, list):
            raise ValueError(f"collections.{name} must be a list")
        _require_fields(rows, required_fields, f"collections.{name}")

    relations = payload.get("relations")
    if not isinstance(relations, list):
        raise ValueError("relations must be a list")
    _require_fields(relations, RELATION_FIELDS, "relations")

    timeline = payload.get("timeline")
    if not isinstance(timeline, list):
        raise ValueError("timeline must be a list")
    _require_fields(timeline, TIMELINE_FIELDS, "timeline")
