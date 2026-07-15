#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import sys
import time
from pathlib import Path
from urllib.error import URLError
from urllib.request import urlopen

from sync_portal_data import SITE_ROOT, find_repo_root, now_iso, sha256_file, summarize_payload


def default_python_bin() -> str:
    candidates = [
        os.environ.get("PYTHON_BIN", "").strip(),
        "/Users/mac/.pyenv/versions/3.10.14/bin/python3",
        sys.executable,
    ]
    for candidate in candidates:
        if candidate and Path(candidate).exists():
            return candidate
    return sys.executable


def git(*args: str, cwd: Path = SITE_ROOT, check: bool = True) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", *args],
        cwd=cwd,
        check=check,
        text=True,
        capture_output=True,
    )


def sync_site_data(*, repo_root: Path, python_bin: str) -> dict[str, object]:
    command = [
        python_bin,
        str(SITE_ROOT / "scripts" / "sync_portal_data.py"),
        "--repo-root",
        str(repo_root),
    ]
    run = subprocess.run(command, check=True, text=True, capture_output=True)
    return json.loads(run.stdout)


def current_branch() -> str:
    return git("rev-parse", "--abbrev-ref", "HEAD").stdout.strip()


def origin_url() -> str:
    return git("remote", "get-url", "origin").stdout.strip()


def derive_pages_url(remote_url: str) -> str:
    trimmed = remote_url.strip()
    if trimmed.endswith(".git"):
        trimmed = trimmed[:-4]
    if trimmed.startswith("git@github.com:"):
        trimmed = trimmed.replace("git@github.com:", "https://github.com/", 1)
    if not trimmed.startswith("https://github.com/"):
        raise ValueError(f"Unsupported GitHub remote URL: {remote_url}")
    parts = trimmed.rstrip("/").split("/")
    owner, repo = parts[-2], parts[-1]
    if repo == f"{owner}.github.io":
        return f"https://{owner}.github.io/"
    return f"https://{owner}.github.io/{repo}/"


def repo_changes() -> list[str]:
    status = git("status", "--short").stdout.splitlines()
    return [line for line in status if line.strip()]


def commit_all(*, message: str) -> str:
    git("add", "-A")
    if git("diff", "--cached", "--quiet", cwd=SITE_ROOT, check=False).returncode == 0:
        return git("rev-parse", "HEAD").stdout.strip()
    git("commit", "-m", message)
    return git("rev-parse", "HEAD").stdout.strip()


def push_current_branch(branch: str) -> None:
    subprocess.run(["git", "push", "origin", branch], cwd=SITE_ROOT, check=True, text=True)


def sha256_bytes(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def fetch_bytes(url: str, *, timeout_seconds: int = 20) -> bytes:
    with urlopen(url, timeout=timeout_seconds) as response:  # noqa: S310 - fixed public URL verification
        return response.read()


def verify_public_site(
    *,
    pages_url: str,
    expected_site_data_sha: str,
    attempts: int,
    sleep_seconds: int,
) -> dict[str, object]:
    index_url = pages_url
    site_data_url = f"{pages_url.rstrip('/')}/data/site-data.json"
    last_error = ""
    for attempt in range(1, attempts + 1):
        try:
            index_html = fetch_bytes(index_url)
            site_data = fetch_bytes(site_data_url)
            remote_sha = sha256_bytes(site_data)
            if b"site-data.json" not in index_html:
                raise ValueError("index.html does not reference site-data.json")
            if remote_sha != expected_site_data_sha:
                raise ValueError(
                    f"remote site-data sha mismatch: expected {expected_site_data_sha}, got {remote_sha}"
                )
            return {
                "status": "passed",
                "attempt": attempt,
                "index_url": index_url,
                "site_data_url": site_data_url,
                "remote_site_data_sha256": remote_sha,
            }
        except (URLError, ValueError) as exc:
            last_error = str(exc)
            if attempt < attempts:
                time.sleep(max(1, sleep_seconds))
    return {
        "status": "failed",
        "attempt": attempts,
        "index_url": index_url,
        "site_data_url": site_data_url,
        "remote_site_data_sha256": "",
        "error": last_error,
    }


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Build, publish, and verify the KFC knowledge portal demo."
    )
    parser.add_argument("--repo-root", default=str(find_repo_root()))
    parser.add_argument("--python-bin", default=default_python_bin())
    parser.add_argument("--pages-url", default="")
    parser.add_argument("--commit-message", default="")
    parser.add_argument("--skip-push", action="store_true")
    parser.add_argument("--skip-verify", action="store_true")
    parser.add_argument("--verify-attempts", type=int, default=12)
    parser.add_argument("--verify-sleep-seconds", type=int, default=10)
    args = parser.parse_args()

    repo_root = Path(args.repo_root).expanduser().resolve()
    sync_result = sync_site_data(repo_root=repo_root, python_bin=args.python_bin)
    site_data_path = SITE_ROOT / "data" / "site-data.json"
    site_data_sha = sha256_file(site_data_path)
    site_data_summary = summarize_payload(site_data_path)
    branch = current_branch()
    remote_url = origin_url()
    pages_url = args.pages_url.strip() or derive_pages_url(remote_url)
    changes = repo_changes()
    commit_message = args.commit_message.strip() or f"Publish portal site {now_iso()}"

    commit_sha = commit_all(message=commit_message)
    committed = bool(changes)

    if committed and not args.skip_push:
        push_current_branch(branch)

    verify_result: dict[str, object]
    if args.skip_verify:
        verify_result = {"status": "skipped"}
    else:
        verify_result = verify_public_site(
            pages_url=pages_url,
            expected_site_data_sha=site_data_sha,
            attempts=max(1, args.verify_attempts),
            sleep_seconds=max(1, args.verify_sleep_seconds),
        )

    result = {
        "status": "success" if verify_result.get("status") in {"passed", "skipped"} else "failed",
        "generated_at": now_iso(),
        "repo_root": str(repo_root),
        "site_root": str(SITE_ROOT),
        "python_bin": args.python_bin,
        "branch": branch,
        "origin_url": remote_url,
        "pages_url": pages_url,
        "changes_before_commit": changes,
        "committed": committed,
        "pushed": committed and not args.skip_push,
        "commit_sha": commit_sha,
        "sync_result": sync_result,
        "site_data_summary": site_data_summary,
        "site_data_sha256": site_data_sha,
        "verify": verify_result,
    }
    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
    return 0 if result["status"] == "success" else 1


if __name__ == "__main__":
    raise SystemExit(main())
