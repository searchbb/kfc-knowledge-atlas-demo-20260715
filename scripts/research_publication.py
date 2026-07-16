"""Shared safety checks for verified public research publications."""

from __future__ import annotations

import hashlib
import re
from datetime import datetime
from pathlib import Path
from typing import Any


VERIFIED_ADMISSION = "verified_research_job_v1"
REPORT_ID_RE = re.compile(r"^[a-z0-9][a-z0-9-]{2,95}$")
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
EMAIL_RE = re.compile(r"(?<![\w.+-])[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}(?![\w.-])")
WINDOWS_PATH_RE = re.compile(r"[A-Za-z]:\\")
PROCESS_PATH_MARKERS = {
    "prompt",
    "draft",
    "evidence_ledger",
    "review",
    "audit",
    "checklist",
    "source_notes",
    "gpt_call",
}
PRIVATE_CONTENT_MARKERS = (
    "requester_email",
    "recipient_email",
    "submitter_email",
    "private_prompt",
    "intake_payload",
)
PRIVATE_PROVENANCE_MARKERS = (
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
    "据内部",
    "我司内部",
    "meeting minutes",
    "internal meeting",
    "user-uploaded material",
    "confidential material",
)


class ResearchPublicationError(ValueError):
    pass


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def parse_publication_time(value: Any) -> str:
    text = str(value or "").strip()
    if not text:
        raise ResearchPublicationError("published_at_is_required")
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ResearchPublicationError("published_at_must_be_iso8601") from exc
    if parsed.tzinfo is None:
        raise ResearchPublicationError("published_at_requires_timezone")
    return parsed.isoformat().replace("+00:00", "Z")


def public_content_violation(text: str) -> str:
    if "/Users/" in text or WINDOWS_PATH_RE.search(text):
        return "absolute_workstation_path"
    if EMAIL_RE.search(text):
        return "email_address"
    lowered = text.lower()
    for marker in PRIVATE_CONTENT_MARKERS:
        if marker in lowered:
            return f"private_marker:{marker}"
    for marker in PRIVATE_PROVENANCE_MARKERS:
        if marker.lower() in lowered:
            return "private_provenance"
    return ""


def validate_verified_manifest_row(row: dict[str, Any], *, repo_root: Path) -> Path:
    if str(row.get("admission") or "") != VERIFIED_ADMISSION:
        raise ResearchPublicationError("unsupported_verified_admission")
    report_id = str(row.get("id") or "").strip()
    if not REPORT_ID_RE.fullmatch(report_id):
        raise ResearchPublicationError("invalid_public_report_id")
    category = str(row.get("category") or "").strip()
    if not category or len(category) > 40 or any(ord(char) < 32 for char in category):
        raise ResearchPublicationError("invalid_publication_category")
    relative_path = str(row.get("path") or "").strip()
    candidate = Path(relative_path)
    if not relative_path or candidate.is_absolute() or candidate.suffix.lower() != ".md":
        raise ResearchPublicationError("public_report_path_must_be_relative_markdown")
    lowered_path = relative_path.lower()
    if any(marker in lowered_path for marker in PROCESS_PATH_MARKERS):
        raise ResearchPublicationError("process_artifact_path_is_not_publishable")
    resolved_root = repo_root.expanduser().resolve()
    resolved_path = (resolved_root / candidate).resolve()
    try:
        resolved_path.relative_to(resolved_root)
    except ValueError as exc:
        raise ResearchPublicationError("public_report_path_escapes_repository") from exc
    if not resolved_path.is_file():
        raise ResearchPublicationError("public_report_file_missing")
    expected_hash = str(row.get("sha256") or "").strip().lower()
    if not SHA256_RE.fullmatch(expected_hash):
        raise ResearchPublicationError("invalid_public_report_sha256")
    if sha256_file(resolved_path) != expected_hash:
        raise ResearchPublicationError("public_report_sha256_mismatch")
    parse_publication_time(row.get("published_at"))
    parse_publication_time(row.get("validated_at"))
    violation = public_content_violation(resolved_path.read_text(encoding="utf-8"))
    if violation:
        raise ResearchPublicationError(f"public_report_contains_{violation}")
    return resolved_path
