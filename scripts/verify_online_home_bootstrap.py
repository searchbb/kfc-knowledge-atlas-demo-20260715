#!/usr/bin/env python3
from __future__ import annotations

import argparse
import gzip
import hashlib
import html
import json
import re
import time
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import urljoin
from urllib.request import Request, urlopen


SITE_ROOT = Path(__file__).resolve().parents[1]


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def fetch_bytes(url: str, timeout: float) -> bytes:
    request = Request(url, headers={"Accept-Encoding": "gzip", "Cache-Control": "no-cache"})
    with urlopen(request, timeout=timeout) as response:
        payload = response.read()
        if response.headers.get("Content-Encoding", "").lower() == "gzip":
            payload = gzip.decompress(payload)
        return payload


def verify_once(base_url: str, timeout: float) -> dict[str, object]:
    cache_bust = f"verify={time.time_ns()}"
    index_url = f"{urljoin(base_url, 'index.html')}?{cache_bust}"
    route_url = f"{urljoin(base_url, 'data/route-home.json')}?{cache_bust}"
    remote_index = fetch_bytes(index_url, timeout)
    remote_route = fetch_bytes(route_url, timeout)
    index_text = remote_index.decode("utf-8")
    route_home = json.loads(remote_route)
    match = re.search(r'data-home-bootstrap data-generated-at="([^"]+)"', index_text)
    bootstrap_generated_at = html.unescape(match.group(1)) if match else ""
    route_generated_at = str(route_home.get("generatedAt") or "")
    news = list(dict(route_home.get("collections") or {}).get("news") or [])
    latest = sorted(
        news,
        key=lambda item: str(item.get("publishedAt") or item.get("updatedAt") or ""),
        reverse=True,
    )
    latest_title = str(latest[0].get("title") or "") if latest else ""
    local_index = (SITE_ROOT / "index.html").read_bytes()
    local_route = (SITE_ROOT / "data" / "route-home.json").read_bytes()
    errors: list[str] = []
    if not bootstrap_generated_at:
        errors.append("remote index is missing data-home-bootstrap generatedAt")
    if bootstrap_generated_at != route_generated_at:
        errors.append("remote bootstrap generatedAt differs from remote route-home")
    if latest_title and html.escape(latest_title) not in index_text:
        errors.append("remote static home does not contain the latest route-home headline")
    if sha256_bytes(remote_index) != sha256_bytes(local_index):
        errors.append("remote index SHA256 differs from local index")
    if sha256_bytes(remote_route) != sha256_bytes(local_route):
        errors.append("remote route-home SHA256 differs from local route-home")
    return {
        "status": "passed" if not errors else "failed",
        "base_url": base_url,
        "bootstrap_generated_at": bootstrap_generated_at,
        "route_home_generated_at": route_generated_at,
        "latest_title": latest_title,
        "remote_index_sha256": sha256_bytes(remote_index),
        "local_index_sha256": sha256_bytes(local_index),
        "remote_route_home_sha256": sha256_bytes(remote_route),
        "local_route_home_sha256": sha256_bytes(local_route),
        "errors": errors,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Verify the published static home and route-home are one build.")
    parser.add_argument("--base-url", default="https://searchbb.github.io/ai-signals-observer/")
    parser.add_argument("--attempts", type=int, default=18)
    parser.add_argument("--sleep-seconds", type=float, default=8.0)
    parser.add_argument("--timeout", type=float, default=30.0)
    args = parser.parse_args()
    base_url = args.base_url.rstrip("/") + "/"
    last_result: dict[str, object] = {}
    last_error = ""
    for attempt in range(1, max(1, args.attempts) + 1):
        try:
            last_result = verify_once(base_url, args.timeout)
            last_result["attempt"] = attempt
            if last_result["status"] == "passed":
                print(json.dumps(last_result, ensure_ascii=False, indent=2, sort_keys=True))
                return 0
        except (HTTPError, URLError, TimeoutError, OSError, ValueError, json.JSONDecodeError) as error:
            last_error = str(error)
        if attempt < max(1, args.attempts):
            time.sleep(max(0.0, args.sleep_seconds))
    if last_error:
        last_result["transport_error"] = last_error
    last_result["status"] = "failed"
    print(json.dumps(last_result, ensure_ascii=False, indent=2, sort_keys=True))
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
