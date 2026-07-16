#!/usr/bin/env python3
"""Prove a portal release commit can be reverted without touching production."""

from __future__ import annotations

import argparse
import json
import subprocess
import tempfile
from pathlib import Path


SITE_ROOT = Path(__file__).resolve().parents[1]


def git(*args: str, cwd: Path) -> str:
    return subprocess.run(
        ["git", *args], cwd=cwd, check=True, text=True, capture_output=True
    ).stdout.strip()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--site-root", default=str(SITE_ROOT))
    parser.add_argument("--release-commit", default="HEAD")
    args = parser.parse_args()
    source = Path(args.site_root).expanduser().resolve()
    release_commit = git("rev-parse", args.release_commit, cwd=source)
    previous_commit = git("rev-parse", f"{release_commit}^", cwd=source)
    previous_tree = git("rev-parse", f"{previous_commit}^{{tree}}", cwd=source)
    with tempfile.TemporaryDirectory(prefix="portal-rollback-") as temp_dir:
        clone = Path(temp_dir) / "site"
        subprocess.run(
            ["git", "clone", "--quiet", "--no-hardlinks", str(source), str(clone)],
            check=True,
        )
        git("checkout", "--detach", release_commit, cwd=clone)
        git("-c", "user.name=Portal Rollback Test", "-c", "user.email=rollback@example.invalid", "revert", "--no-edit", release_commit, cwd=clone)
        reverted_tree = git("rev-parse", "HEAD^{tree}", cwd=clone)
        required_files = ["index.html", "app.js", "styles.css", "data/site-data.json"]
        missing = [name for name in required_files if not (clone / name).exists()]
        if reverted_tree != previous_tree or missing:
            raise RuntimeError(
                f"rollback mismatch: expected tree {previous_tree}, got {reverted_tree}, missing={missing}"
            )
    print(json.dumps({
        "status": "passed",
        "release_commit": release_commit,
        "previous_commit": previous_commit,
        "previous_tree": previous_tree,
        "reverted_tree": reverted_tree,
        "production_mutated": False,
    }, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
