#!/usr/bin/env python3
"""Admit one locally verified public research job to the static-site manifest."""

from __future__ import annotations

import argparse
import fcntl
import hashlib
import json
import os
import sqlite3
import subprocess
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from research_publication import (
    REPORT_ID_RE,
    VERIFIED_ADMISSION,
    ResearchPublicationError,
    parse_publication_time,
    sha256_file,
    validate_verified_manifest_row,
)


SITE_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_MANIFEST = Path(__file__).resolve().with_name("research_publication_manifest.json")


def _json_object(value: Any, *, error: str) -> dict[str, Any]:
    try:
        parsed = json.loads(str(value or "{}"))
    except json.JSONDecodeError as exc:
        raise ResearchPublicationError(error) from exc
    if not isinstance(parsed, dict):
        raise ResearchPublicationError(error)
    return parsed


def _resolve_artifact_path(value: str, repo_root: Path) -> Path:
    path = Path(value).expanduser()
    return path.resolve() if path.is_absolute() else (repo_root / path).resolve()


def _public_report_id(job_id: str, metadata: dict[str, Any]) -> str:
    explicit = str(metadata.get("public_report_id") or metadata.get("publication_id") or "").strip()
    if explicit:
        if not REPORT_ID_RE.fullmatch(explicit):
            raise ResearchPublicationError("invalid_metadata_public_report_id")
        return explicit
    return f"research-{hashlib.sha256(job_id.encode('utf-8')).hexdigest()[:16]}"


def _read_verified_job(*, db_path: Path, repo_root: Path, job_id: str) -> dict[str, Any]:
    if not db_path.is_file():
        raise ResearchPublicationError("research_control_database_missing")
    connection = sqlite3.connect(f"{db_path.resolve().as_uri()}?mode=ro", uri=True)
    connection.row_factory = sqlite3.Row
    try:
        job = connection.execute(
            """SELECT job_id,title,visibility,verification_status,final_report_path,
                      metadata_json,updated_at
               FROM research_jobs WHERE job_id=?""",
            (job_id,),
        ).fetchone()
        if job is None:
            raise ResearchPublicationError("research_job_not_found")
        if str(job["visibility"]) != "public":
            raise ResearchPublicationError("private_research_job_cannot_be_published")
        if str(job["verification_status"]) != "passed":
            raise ResearchPublicationError("research_job_verification_not_passed")
        node = connection.execute(
            """SELECT status,output_json,updated_at
               FROM research_job_nodes
               WHERE job_id=? AND node_type='report_validation'
               ORDER BY ordinal DESC LIMIT 1""",
            (job_id,),
        ).fetchone()
        if node is None or str(node["status"]) != "completed":
            raise ResearchPublicationError("report_validation_node_not_completed")
        evidence = _json_object(node["output_json"], error="invalid_report_validation_evidence")
        if str(evidence.get("outcome") or "") != "passed":
            raise ResearchPublicationError("report_validation_outcome_not_passed")
        if str(evidence.get("validator_status") or evidence.get("validation_status") or "") != "passed":
            raise ResearchPublicationError("validator_evidence_not_passed")
        if str(evidence.get("acceptance_status") or evidence.get("final_verdict") or "") not in {
            "accepted",
            "passed",
        }:
            raise ResearchPublicationError("final_acceptance_not_passed")
        if str(evidence.get("information_safety_status") or "") != "passed":
            raise ResearchPublicationError("information_safety_review_not_passed")
        if evidence.get("public_sources_only") is not True:
            raise ResearchPublicationError("public_sources_only_not_confirmed")
        report_path = _resolve_artifact_path(str(job["final_report_path"] or ""), repo_root)
        try:
            relative_path = report_path.relative_to(repo_root).as_posix()
        except ValueError as exc:
            raise ResearchPublicationError("final_report_path_escapes_repository") from exc
        if not report_path.is_file():
            raise ResearchPublicationError("final_report_file_missing")
        report_hash = sha256_file(report_path)
        if str(evidence.get("final_report_sha256") or "").lower() != report_hash:
            raise ResearchPublicationError("validation_evidence_hash_mismatch")
        artifacts = connection.execute(
            """SELECT relative_path,content_hash,visibility
               FROM research_job_artifacts
               WHERE job_id=? AND artifact_type='final_report'""",
            (job_id,),
        ).fetchall()
        artifact_verified = any(
            str(row["visibility"]) == "public"
            and str(row["content_hash"] or "").lower() == report_hash
            and _resolve_artifact_path(str(row["relative_path"] or ""), repo_root) == report_path
            for row in artifacts
        )
        if not artifact_verified:
            raise ResearchPublicationError("public_final_report_artifact_not_verified")
        metadata = _json_object(job["metadata_json"], error="invalid_research_job_metadata")
        return {
            "id": _public_report_id(str(job["job_id"]), metadata),
            "path": relative_path,
            "category": str(metadata.get("publication_category") or "深度研究").strip(),
            "sha256": report_hash,
            "admission": VERIFIED_ADMISSION,
            "validated_at": parse_publication_time(node["updated_at"] or job["updated_at"]),
        }
    except sqlite3.Error as exc:
        raise ResearchPublicationError(f"research_control_database_error:{exc}") from exc
    finally:
        connection.close()


def _default_lock_path() -> Path:
    result = subprocess.run(
        ["git", "rev-parse", "--git-path", "public-research-admission.lock"],
        cwd=SITE_ROOT,
        check=True,
        capture_output=True,
        text=True,
    )
    value = Path(result.stdout.strip()).expanduser()
    return value.resolve() if value.is_absolute() else (SITE_ROOT / value).resolve()


def _atomic_write_json(path: Path, value: dict[str, Any]) -> None:
    rendered = json.dumps(value, ensure_ascii=False, indent=2) + "\n"
    with tempfile.NamedTemporaryFile(
        mode="w",
        encoding="utf-8",
        dir=path.parent,
        prefix=f".{path.name}.",
        suffix=".tmp",
        delete=False,
    ) as handle:
        temporary = Path(handle.name)
        handle.write(rendered)
        handle.flush()
        os.fsync(handle.fileno())
    try:
        temporary.replace(path)
    finally:
        if temporary.exists():
            temporary.unlink()


def admit_verified_job(
    *,
    db_path: Path,
    repo_root: Path,
    manifest_path: Path,
    lock_path: Path,
    job_id: str,
    published_at: str | None = None,
) -> dict[str, Any]:
    repo_root = repo_root.expanduser().resolve()
    row = _read_verified_job(db_path=db_path, repo_root=repo_root, job_id=job_id)
    row["published_at"] = parse_publication_time(
        published_at or datetime.now(timezone.utc).isoformat()
    )
    validate_verified_manifest_row(row, repo_root=repo_root)
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    with lock_path.open("a+", encoding="utf-8") as lock_handle:
        fcntl.flock(lock_handle.fileno(), fcntl.LOCK_EX)
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        if not isinstance(manifest, dict) or not isinstance(manifest.get("reports"), list):
            raise ResearchPublicationError("research_manifest_must_contain_reports_list")
        reports = list(manifest["reports"])
        if not all(isinstance(existing, dict) for existing in reports):
            raise ResearchPublicationError("research_manifest_report_must_be_object")
        for existing in reports:
            same_id = str(existing.get("id") or "") == row["id"]
            same_path = str(existing.get("path") or "") == row["path"]
            same_hash = str(existing.get("sha256") or "") == row["sha256"]
            if same_id or same_path or same_hash:
                if (
                    same_id
                    and same_path
                    and same_hash
                    and str(existing.get("admission") or "") == VERIFIED_ADMISSION
                ):
                    validate_verified_manifest_row(existing, repo_root=repo_root)
                    return {"status": "existing", "report": existing}
                raise ResearchPublicationError("research_manifest_identity_collision")
        reports.insert(0, row)
        manifest["reports"] = reports
        _atomic_write_json(manifest_path, manifest)
    return {"status": "admitted", "report": row}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", type=Path, required=True)
    parser.add_argument("--repo-root", type=Path, required=True)
    parser.add_argument("--job-id", required=True)
    parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    parser.add_argument("--lock-file", type=Path, default=None)
    parser.add_argument("--published-at", default="")
    args = parser.parse_args()
    try:
        result = admit_verified_job(
            db_path=args.db.expanduser().resolve(),
            repo_root=args.repo_root.expanduser().resolve(),
            manifest_path=args.manifest.expanduser().resolve(),
            lock_path=(args.lock_file.expanduser().resolve() if args.lock_file else _default_lock_path()),
            job_id=args.job_id,
            published_at=args.published_at or None,
        )
    except (OSError, json.JSONDecodeError, ResearchPublicationError) as exc:
        print(json.dumps({"status": "rejected", "error": str(exc)}, ensure_ascii=False))
        return 1
    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
