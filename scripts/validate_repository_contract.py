#!/usr/bin/env python3
"""Validate the renamed public repository with bounded GitHub API retry."""

from __future__ import annotations

import json
import subprocess
import time
from pathlib import Path


SITE_ROOT = Path(__file__).resolve().parents[1]
REPOSITORY = "searchbb/ai-signals-observer"
EXPECTED_ORIGIN = "https://github.com/searchbb/ai-signals-observer.git"


def run(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(args, text=True, capture_output=True, check=False)


def main() -> int:
    last_error = ""
    repo: dict[str, str] = {}
    attempt = 0
    for attempt in range(1, 6):
        result = run("gh", "repo", "view", REPOSITORY, "--json", "name,url,visibility")
        if result.returncode == 0:
            repo = json.loads(result.stdout)
            break
        last_error = (result.stderr or result.stdout).strip()
        time.sleep(attempt)
    if not repo:
        raise RuntimeError(f"GitHub repository lookup failed after {attempt} attempts: {last_error}")
    remote = run("git", "-C", str(SITE_ROOT), "remote", "get-url", "origin")
    if remote.returncode != 0:
        raise RuntimeError((remote.stderr or remote.stdout).strip())
    origin = remote.stdout.strip()
    assert repo["name"] == "ai-signals-observer", repo
    assert repo["visibility"] == "PUBLIC", repo
    assert origin == EXPECTED_ORIGIN, origin
    print(json.dumps({"status": "passed", "attempt": attempt, "repository": repo, "origin": origin}, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
