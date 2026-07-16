#!/usr/bin/env python3
from __future__ import annotations

import argparse
import fcntl
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


def push_current_branch(branch: str, *, attempts: int, sleep_seconds: int) -> int:
    last_error = ""
    for attempt in range(1, attempts + 1):
        result = subprocess.run(
            ["git", "push", "origin", branch],
            cwd=SITE_ROOT,
            check=False,
            text=True,
            capture_output=True,
        )
        if result.returncode == 0:
            return attempt
        last_error = (result.stderr or result.stdout).strip()
        if attempt < attempts:
            time.sleep(max(1, sleep_seconds))
    raise RuntimeError(f"git push failed after {attempts} attempts: {last_error}")


def sha256_bytes(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def research_asset_hashes() -> dict[str, str]:
    root = SITE_ROOT / "assets" / "research"
    if not root.exists():
        return {}
    return {
        path.relative_to(SITE_ROOT).as_posix(): sha256_file(path)
        for path in sorted(root.rglob("*"))
        if path.is_file()
    }


def fetch_bytes(url: str, *, timeout_seconds: int = 20) -> bytes:
    with urlopen(url, timeout=timeout_seconds) as response:  # noqa: S310 - fixed public URL verification
        return response.read()


def verify_public_site(
    *,
    pages_url: str,
    expected_site_data_sha: str,
    expected_index_sha: str,
    expected_app_js_sha: str,
    expected_styles_sha: str,
    expected_asset_hashes: dict[str, str],
    attempts: int,
    sleep_seconds: int,
) -> dict[str, object]:
    cache_key = expected_site_data_sha[:16]
    index_url = f"{pages_url}?verify={cache_key}"
    app_js_url = f"{pages_url.rstrip('/')}/app.js?verify={cache_key}"
    styles_url = f"{pages_url.rstrip('/')}/styles.css?verify={cache_key}"
    site_data_url = f"{pages_url.rstrip('/')}/data/site-data.json?verify={cache_key}"
    last_error = ""
    for attempt in range(1, attempts + 1):
        try:
            index_html = fetch_bytes(index_url)
            app_js = fetch_bytes(app_js_url)
            styles = fetch_bytes(styles_url)
            site_data = fetch_bytes(site_data_url)
            remote_index_sha = sha256_bytes(index_html)
            remote_app_js_sha = sha256_bytes(app_js)
            remote_styles_sha = sha256_bytes(styles)
            remote_sha = sha256_bytes(site_data)
            if b'<script type="module" src="./app.js"></script>' not in index_html:
                raise ValueError("index.html does not reference app.js")
            if b'fetch("./data/site-data.json"' not in app_js:
                raise ValueError("app.js does not fetch site-data.json")
            if b'<link rel="stylesheet" href="./styles.css"' not in index_html:
                raise ValueError("index.html does not reference styles.css")
            if remote_index_sha != expected_index_sha:
                raise ValueError(
                    f"remote index sha mismatch: expected {expected_index_sha}, got {remote_index_sha}"
                )
            if remote_app_js_sha != expected_app_js_sha:
                raise ValueError(
                    f"remote app.js sha mismatch: expected {expected_app_js_sha}, got {remote_app_js_sha}"
                )
            if remote_styles_sha != expected_styles_sha:
                raise ValueError(
                    f"remote styles.css sha mismatch: expected {expected_styles_sha}, got {remote_styles_sha}"
                )
            if remote_sha != expected_site_data_sha:
                raise ValueError(
                    f"remote site-data sha mismatch: expected {expected_site_data_sha}, got {remote_sha}"
                )
            remote_asset_hashes: dict[str, str] = {}
            for relative_path, expected_hash in expected_asset_hashes.items():
                asset_url = f"{pages_url.rstrip('/')}/{relative_path}?verify={cache_key}"
                remote_hash = sha256_bytes(fetch_bytes(asset_url))
                if remote_hash != expected_hash:
                    raise ValueError(
                        f"remote asset sha mismatch for {relative_path}: expected {expected_hash}, got {remote_hash}"
                    )
                remote_asset_hashes[relative_path] = remote_hash
            return {
                "status": "passed",
                "attempt": attempt,
                "index_url": index_url,
                "app_js_url": app_js_url,
                "styles_url": styles_url,
                "site_data_url": site_data_url,
                "remote_site_data_sha256": remote_sha,
                "remote_index_sha256": remote_index_sha,
                "remote_app_js_sha256": remote_app_js_sha,
                "remote_styles_sha256": remote_styles_sha,
                "remote_research_asset_sha256": remote_asset_hashes,
            }
        except (URLError, ValueError) as exc:
            last_error = str(exc)
            if attempt < attempts:
                time.sleep(max(1, sleep_seconds))
    return {
        "status": "failed",
        "attempt": attempts,
        "index_url": index_url,
        "app_js_url": app_js_url,
        "site_data_url": site_data_url,
        "remote_site_data_sha256": "",
        "error": last_error,
    }


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Build, publish, and verify the AI Signals Observer site."
    )
    parser.add_argument("--repo-root", default="")
    parser.add_argument("--python-bin", default=default_python_bin())
    parser.add_argument("--pages-url", default="")
    parser.add_argument("--commit-message", default="")
    parser.add_argument("--skip-push", action="store_true")
    parser.add_argument("--skip-verify", action="store_true")
    parser.add_argument("--verify-attempts", type=int, default=12)
    parser.add_argument("--verify-sleep-seconds", type=int, default=10)
    parser.add_argument("--push-attempts", type=int, default=3)
    parser.add_argument("--push-sleep-seconds", type=int, default=5)
    parser.add_argument("--lock-timeout-seconds", type=int, default=300)
    args = parser.parse_args()

    lock_path = SITE_ROOT / ".git" / "portal-publish.lock"
    lock_handle = lock_path.open("a+", encoding="utf-8")
    lock_deadline = time.monotonic() + max(1, args.lock_timeout_seconds)
    while True:
        try:
            fcntl.flock(lock_handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            break
        except BlockingIOError:
            if time.monotonic() >= lock_deadline:
                raise RuntimeError("timed out waiting for the portal publish lock")
            time.sleep(1)

    repo_root = Path(args.repo_root or str(find_repo_root())).expanduser().resolve()
    sync_result = sync_site_data(repo_root=repo_root, python_bin=args.python_bin)
    site_data_path = SITE_ROOT / "data" / "site-data.json"
    site_data_sha = sha256_file(site_data_path)
    index_sha = sha256_file(SITE_ROOT / "index.html")
    app_js_sha = sha256_file(SITE_ROOT / "app.js")
    styles_sha = sha256_file(SITE_ROOT / "styles.css")
    asset_hashes = research_asset_hashes()
    site_data_summary = summarize_payload(site_data_path)
    branch = current_branch()
    remote_url = origin_url()
    pages_url = args.pages_url.strip() or derive_pages_url(remote_url)
    changes = repo_changes()
    commit_message = args.commit_message.strip() or f"Publish portal site {now_iso()}"

    commit_sha = commit_all(message=commit_message)
    committed = bool(changes)

    push_attempt = 0
    if committed and not args.skip_push:
        push_attempt = push_current_branch(
            branch,
            attempts=max(1, args.push_attempts),
            sleep_seconds=max(1, args.push_sleep_seconds),
        )

    verify_result: dict[str, object]
    if args.skip_verify:
        verify_result = {"status": "skipped"}
    else:
        verify_result = verify_public_site(
            pages_url=pages_url,
            expected_site_data_sha=site_data_sha,
            expected_index_sha=index_sha,
            expected_app_js_sha=app_js_sha,
            expected_styles_sha=styles_sha,
            expected_asset_hashes=asset_hashes,
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
        "push_attempt": push_attempt,
        "commit_sha": commit_sha,
        "sync_result": sync_result,
        "site_data_summary": site_data_summary,
        "site_data_sha256": site_data_sha,
        "index_sha256": index_sha,
        "app_js_sha256": app_js_sha,
        "styles_sha256": styles_sha,
        "research_asset_sha256": asset_hashes,
        "verify": verify_result,
    }
    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
    return 0 if result["status"] == "success" else 1


if __name__ == "__main__":
    raise SystemExit(main())
