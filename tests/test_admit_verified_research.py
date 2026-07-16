from __future__ import annotations

import hashlib
import json
import sqlite3
import sys
import tempfile
import unittest
from pathlib import Path


SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

from admit_verified_research import admit_verified_job
from build_site_data import parse_research_report, research_candidates
from research_publication import ResearchPublicationError
from sync_portal_data import build_route_indexes, build_site_index


class VerifiedResearchAdmissionTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.repo_root = self.root / "kfc"
        self.report = self.repo_root / "research" / "jobs" / "final_report.md"
        self.report.parent.mkdir(parents=True)
        self.report.write_text("# 一份已验证的公开研究\n\n公开证据与研究结论。\n", encoding="utf-8")
        self.report_hash = hashlib.sha256(self.report.read_bytes()).hexdigest()
        self.db = self.root / "control.sqlite3"
        self.manifest = self.root / "manifest.json"
        self.lock = self.root / "admission.lock"
        self.manifest.write_text(
            json.dumps({"version": 1, "reports": []}, ensure_ascii=False),
            encoding="utf-8",
        )
        self._seed_job()

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def _seed_job(self, *, visibility: str = "public", verification: str = "passed") -> None:
        with sqlite3.connect(self.db) as connection:
            connection.executescript(
                """
                CREATE TABLE research_jobs(
                    job_id TEXT PRIMARY KEY,title TEXT,visibility TEXT,verification_status TEXT,
                    final_report_path TEXT,metadata_json TEXT,updated_at TEXT
                );
                CREATE TABLE research_job_nodes(
                    job_id TEXT,node_type TEXT,status TEXT,output_json TEXT,updated_at TEXT,ordinal INTEGER
                );
                CREATE TABLE research_job_artifacts(
                    job_id TEXT,artifact_type TEXT,relative_path TEXT,content_hash TEXT,visibility TEXT
                );
                """
            )
            evidence = {
                "outcome": "passed",
                "validator_status": "passed",
                "acceptance_status": "accepted",
                "final_report_sha256": self.report_hash,
                "information_safety_status": "passed",
                "public_sources_only": True,
            }
            connection.execute(
                "INSERT INTO research_jobs VALUES(?,?,?,?,?,?,?)",
                (
                    "rjob_test", "公开研究", visibility, verification, str(self.report),
                    json.dumps({"public_report_id": "verified-public-report", "publication_category": "技术趋势"}),
                    "2026-07-16T10:00:00Z",
                ),
            )
            connection.execute(
                "INSERT INTO research_job_nodes VALUES(?,?,?,?,?,?)",
                (
                    "rjob_test", "report_validation", "completed", json.dumps(evidence),
                    "2026-07-16T10:00:00Z", 9,
                ),
            )
            connection.execute(
                "INSERT INTO research_job_artifacts VALUES(?,?,?,?,?)",
                ("rjob_test", "final_report", str(self.report), self.report_hash, "public"),
            )
            connection.commit()

    def _admit(self):
        return admit_verified_job(
            db_path=self.db,
            repo_root=self.repo_root,
            manifest_path=self.manifest,
            lock_path=self.lock,
            job_id="rjob_test",
            published_at="2026-07-16T10:05:00Z",
        )

    def test_admits_idempotently_and_projects_publication_time(self) -> None:
        first = self._admit()
        first_bytes = self.manifest.read_bytes()
        second = self._admit()

        self.assertEqual(first["status"], "admitted")
        self.assertEqual(second["status"], "existing")
        self.assertEqual(self.manifest.read_bytes(), first_bytes)
        rows = research_candidates(self.repo_root, self.manifest)
        self.assertEqual(len(rows), 1)
        row, path = rows[0]
        self.assertEqual(path, self.report.resolve())
        stage = self.root / "assets-stage"
        stage.mkdir()
        projected = parse_research_report(
            path,
            report_id=row["id"],
            category=row["category"],
            asset_stage_root=stage,
            published_at=row["published_at"],
        )
        self.assertEqual(projected["updatedAt"], "2026-07-16T10:05:00Z")
        self.assertEqual(projected["status"], "published")
        site_index = build_site_index(
            {
                "schemaVersion": "test",
                "generatedAt": "2026-07-16T10:05:01Z",
                "buildMeta": {},
                "stats": {"research": 1},
                "collections": {"research": [projected]},
                "newsMeta": {},
                "relations": [],
                "timeline": [],
            }
        )
        route_root = self.root / "route-data"
        build_route_indexes(site_index, route_root)
        route = json.loads((route_root / "route-research.json").read_text(encoding="utf-8"))
        self.assertEqual(route["collections"]["research"][0]["id"], "verified-public-report")
        self.assertEqual(
            route["collections"]["research"][0]["updatedAt"],
            "2026-07-16T10:05:00Z",
        )

    def test_rejects_private_and_unverified_jobs_without_manifest_mutation(self) -> None:
        baseline = self.manifest.read_bytes()
        with sqlite3.connect(self.db) as connection:
            connection.execute("UPDATE research_jobs SET visibility='private'")
            connection.commit()
        with self.assertRaisesRegex(ResearchPublicationError, "private_research_job"):
            self._admit()
        self.assertEqual(self.manifest.read_bytes(), baseline)

        with sqlite3.connect(self.db) as connection:
            connection.execute("UPDATE research_jobs SET visibility='public',verification_status='failed'")
            connection.commit()
        with self.assertRaisesRegex(ResearchPublicationError, "verification_not_passed"):
            self._admit()
        self.assertEqual(self.manifest.read_bytes(), baseline)

    def test_rejects_changed_or_private_content_without_manifest_mutation(self) -> None:
        baseline = self.manifest.read_bytes()
        self.report.write_text("# 被修改的报告\n", encoding="utf-8")
        with self.assertRaisesRegex(ResearchPublicationError, "hash_mismatch"):
            self._admit()
        self.assertEqual(self.manifest.read_bytes(), baseline)

        private_hash = hashlib.sha256(b"# report\nowner@example.com\n").hexdigest()
        self.report.write_bytes(b"# report\nowner@example.com\n")
        with sqlite3.connect(self.db) as connection:
            evidence = {
                "outcome": "passed", "validator_status": "passed",
                "acceptance_status": "accepted", "final_report_sha256": private_hash,
                "information_safety_status": "passed", "public_sources_only": True,
            }
            connection.execute(
                "UPDATE research_job_nodes SET output_json=?", (json.dumps(evidence),)
            )
            connection.execute(
                "UPDATE research_job_artifacts SET content_hash=?", (private_hash,)
            )
            connection.commit()
        with self.assertRaisesRegex(ResearchPublicationError, "email_address"):
            self._admit()
        self.assertEqual(self.manifest.read_bytes(), baseline)

        unsafe = "# report\n\n根据内部会议形成判断。\n".encode("utf-8")
        unsafe_hash = hashlib.sha256(unsafe).hexdigest()
        self.report.write_bytes(unsafe)
        with sqlite3.connect(self.db) as connection:
            evidence = {
                "outcome": "passed", "validator_status": "passed",
                "acceptance_status": "accepted", "final_report_sha256": unsafe_hash,
                "information_safety_status": "passed", "public_sources_only": True,
            }
            connection.execute(
                "UPDATE research_job_nodes SET output_json=?", (json.dumps(evidence),)
            )
            connection.execute(
                "UPDATE research_job_artifacts SET content_hash=?", (unsafe_hash,)
            )
            connection.commit()
        with self.assertRaisesRegex(ResearchPublicationError, "private_provenance"):
            self._admit()
        self.assertEqual(self.manifest.read_bytes(), baseline)

    def test_build_rejects_report_tampering_after_admission(self) -> None:
        self._admit()
        self.report.write_text("# 已被发布门之后篡改\n", encoding="utf-8")

        with self.assertRaisesRegex(ResearchPublicationError, "sha256_mismatch"):
            research_candidates(self.repo_root, self.manifest)


if __name__ == "__main__":
    unittest.main()
