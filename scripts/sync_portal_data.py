#!/usr/bin/env python3
from __future__ import annotations

import argparse
import gzip
import hashlib
import html
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import quote

from validate_portal_data import validate_portal_file


SITE_ROOT = Path(__file__).resolve().parents[1]
BUILD_SCRIPT = Path(__file__).resolve().with_name("build_site_data.py")
DETAIL_COLLECTION_TYPES = {
    "topics": "topic",
    "issues": "issue",
    "cards": "card",
    "research": "research",
    "articles": "article",
    "news": "news",
}
URL_SAFE_FILENAME_CHARS = "-_.!~*'()"
INDEX_DETAIL_ONLY_FIELDS = {"html", "text", "path", "url"}
INDEX_SUMMARY_LIMITS = {
    "articles": 0,
    "news": 240,
    "research": 600,
    "issues": 600,
    "cards": 600,
    "topics": 600,
}
ROUTE_COLLECTIONS = ("topics", "issues", "cards", "research", "articles", "news")
HOME_STATS_START = "<!-- HOME_STATS_START -->"
HOME_STATS_END = "<!-- HOME_STATS_END -->"
HOME_CONTENT_START = "<!-- HOME_CONTENT_START -->"
HOME_CONTENT_END = "<!-- HOME_CONTENT_END -->"


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def find_repo_root() -> Path:
    for candidate in Path(__file__).resolve().parents:
        if (candidate / "data/semantic_pipeline_v2").exists() and (
            candidate / "data/news_library/news_library.sqlite3"
        ).exists():
            return candidate
    raise SystemExit("Could not infer KFC repo root. Pass --repo-root explicitly.")


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def truncate_text(value: object, limit: int) -> object:
    if not isinstance(value, str):
        return value
    if limit <= 0:
        return ""
    if len(value) <= limit:
        return value
    return f"{value[: limit - 1].rstrip()}…"


def build_site_index(payload: dict[str, object]) -> dict[str, object]:
    collections: dict[str, list[dict[str, object]]] = {}
    for collection_name, rows in dict(payload.get("collections") or {}).items():
        summary_limit = INDEX_SUMMARY_LIMITS.get(collection_name, 600)
        projected_rows: list[dict[str, object]] = []
        for raw_item in list(rows or []):
            item = {
                key: value
                for key, value in dict(raw_item).items()
                if key not in INDEX_DETAIL_ONLY_FIELDS
            }
            if "summary" in item:
                if summary_limit <= 0:
                    item.pop("summary", None)
                else:
                    item["summary"] = truncate_text(item["summary"], summary_limit)
            projected_rows.append(item)
        collections[collection_name] = projected_rows
    return {
        "schemaVersion": payload.get("schemaVersion"),
        "generatedAt": payload.get("generatedAt"),
        "indexVersion": 1,
        "buildMeta": payload.get("buildMeta") or {},
        "stats": payload.get("stats") or {},
        "collections": collections,
        "newsMeta": payload.get("newsMeta") or {},
        "relations": payload.get("relations") or [],
        "timeline": payload.get("timeline") or [],
    }


def route_payload_base(payload: dict[str, object]) -> dict[str, object]:
    return {
        "schemaVersion": payload.get("schemaVersion"),
        "generatedAt": payload.get("generatedAt"),
        "routeIndexVersion": 1,
        "buildMeta": payload.get("buildMeta") or {},
    }


def write_atomic_json(path: Path, payload: dict[str, object]) -> dict[str, object]:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(
        mode="w",
        encoding="utf-8",
        prefix=f".{path.stem}-",
        suffix=".json",
        dir=str(path.parent),
        delete=False,
    ) as handle:
        temp_path = Path(handle.name)
        json.dump(payload, handle, ensure_ascii=False, separators=(",", ":"))
    try:
        raw_bytes = temp_path.read_bytes()
        temp_path.replace(path)
    finally:
        if temp_path.exists():
            temp_path.unlink()
    return {
        "path": str(path),
        "sha256": sha256_file(path),
        "bytes": len(raw_bytes),
        "gzip_bytes": len(gzip.compress(raw_bytes, compresslevel=9, mtime=0)),
    }


def build_route_indexes(index_payload: dict[str, object], output_root: Path) -> dict[str, object]:
    collections = dict(index_payload.get("collections") or {})
    base = route_payload_base(index_payload)
    files: dict[str, dict[str, object]] = {}

    # 首页只需要少量近期内容；各栏目进入时再取自己的完整轻量列表。
    recent_news = sorted(
        list(collections.get("news") or []),
        key=lambda item: str(
            item.get("publishedAt") or item.get("updatedAt") or item.get("mtime") or ""
        ),
        reverse=True,
    )[:30]
    home_payload = {
        **base,
        "route": "home",
        "stats": index_payload.get("stats") or {},
        "newsMeta": index_payload.get("newsMeta") or {},
        "collections": {
            "topics": list(collections.get("topics") or []),
            "research": list(collections.get("research") or []),
            "news": recent_news,
        },
    }
    files["home"] = write_atomic_json(output_root / "route-home.json", home_payload)

    for name in ROUTE_COLLECTIONS:
        route_payload = {
            **base,
            "route": name,
            "collections": {name: list(collections.get(name) or [])},
        }
        if name == "news":
            route_payload["newsMeta"] = index_payload.get("newsMeta") or {}
        files[name] = write_atomic_json(output_root / f"route-{name}.json", route_payload)

    timeline_payload = {
        **base,
        "route": "timeline",
        "timeline": index_payload.get("timeline") or [],
    }
    files["timeline"] = write_atomic_json(output_root / "route-timeline.json", timeline_payload)
    return {
        "status": "success",
        "files": files,
        "max_gzip_bytes": max(int(item["gzip_bytes"]) for item in files.values()),
    }


def bootstrap_text(value: object) -> str:
    text = re.sub(r"[*_~`#>\-]+", " ", str(value or ""))
    return re.sub(r"\s+", " ", text).strip()


def bootstrap_time(item: dict[str, object]) -> str:
    value = str(
        item.get("publishedAt")
        or item.get("updatedAt")
        or item.get("mtime")
        or item.get("lastUpdated")
        or "-"
    )
    return value.replace("T", " ")[:16]


def bootstrap_sort_key(item: dict[str, object]) -> str:
    return str(
        item.get("publishedAt")
        or item.get("updatedAt")
        or item.get("mtime")
        or item.get("lastUpdated")
        or ""
    )


def bootstrap_href(detail_type: str, item: dict[str, object]) -> str:
    item_id = quote(str(item.get("id") or ""), safe=URL_SAFE_FILENAME_CHARS)
    return f"#{detail_type}/{item_id}"


def render_home_bootstrap(home_payload: dict[str, object]) -> tuple[str, str]:
    esc = lambda value: html.escape(str(value or ""), quote=True)
    collections = dict(home_payload.get("collections") or {})
    stats = dict(home_payload.get("stats") or {})
    generated_at = esc(home_payload.get("generatedAt") or "")
    stat_rows = [
        ("新闻资讯", stats.get("news", 0)),
        ("深度研究", stats.get("research", 0)),
        ("专题观察", stats.get("topics", 0)),
        ("分析卡片", stats.get("issues", 0)),
        ("综合研判", stats.get("cards", 0)),
        ("文章解读", stats.get("articles", 0)),
    ]
    stats_html = "\n          ".join(
        ["<p class=\"stats-title\">内容规模</p>"]
        + [
            f'<div class="stat"><p>{label}</p><strong>{int(value or 0):,}</strong></div>'
            for label, value in stat_rows
        ]
    )

    news = sorted(
        list(collections.get("news") or []), key=bootstrap_sort_key, reverse=True
    )[:9]
    research = sorted(
        list(collections.get("research") or []), key=bootstrap_sort_key, reverse=True
    )[:6]
    lead = news[0] if news else None
    if lead:
        lead_html = (
            f'<a class="lead-story" href="{bootstrap_href("news", lead)}">'
            '<span class="news-label">头条</span>'
            f'<h3>{esc(lead.get("title"))}</h3>'
            f'<p>{esc(bootstrap_text(lead.get("summary") or "来自公开信息源的最新动态。"))}</p>'
            f'<time>{esc(bootstrap_time(lead))}</time></a>'
        )
    else:
        lead_html = '<div class="empty">暂无新闻。</div>'
    brief_html = "".join(
        f'<a class="news-brief" href="{bootstrap_href("news", item)}">'
        f'<span>{index:02d}</span><div><strong>{esc(item.get("title"))}</strong>'
        f'<small>{esc(str(item.get("sourceId") or "公开信息").removeprefix("www."))} · '
        f'{esc(bootstrap_time(item)[:10])}</small></div></a>'
        for index, item in enumerate(news[1:], start=2)
    )
    research_html = "".join(
        f'<a class="research-card" href="{bootstrap_href("research", item)}">'
        f'<span>{esc(item.get("category") or "深度研究")}</span>'
        f'<h4>{esc(item.get("title"))}</h4>'
        f'<p>{esc(bootstrap_text(item.get("summary")))}</p>'
        f'<small>{int(item.get("diagramCount") or 0)} 张图表 · {esc(bootstrap_time(item)[:10])}</small></a>'
        for item in research
    )
    content_html = f'''<div class="bootstrap-home" data-home-bootstrap data-generated-at="{generated_at}">
            <section class="news-front">
              <div class="section-heading"><div><p class="eyebrow">今日关注</p><h3>最新 AI 资讯</h3></div><a href="#news">查看全部新闻 →</a></div>
              <div class="lead-grid">{lead_html}<div class="brief-list">{brief_html}</div></div>
            </section>
            <section class="research-front">
              <div class="section-heading"><div><p class="eyebrow">趋势与洞察</p><h3>深度研究</h3></div><a href="#research">查看全部 {len(collections.get("research") or [])} 份研究 →</a></div>
              <div class="research-grid">{research_html}</div>
            </section>
          </div>'''
    return stats_html, content_html


def replace_marked_region(text: str, start: str, end: str, body: str) -> str:
    pattern = re.compile(f"{re.escape(start)}.*?{re.escape(end)}", re.DOTALL)
    replacement = f"{start}\n          {body}\n          {end}"
    updated, count = pattern.subn(replacement, text, count=1)
    if count != 1:
        raise RuntimeError(f"index template marker missing or duplicated: {start}")
    return updated


def sync_home_bootstrap(*, index_path: Path, route_home_path: Path) -> dict[str, object]:
    home_payload = json.loads(route_home_path.read_text(encoding="utf-8"))
    stats_html, content_html = render_home_bootstrap(home_payload)
    text = index_path.read_text(encoding="utf-8")
    text = replace_marked_region(text, HOME_STATS_START, HOME_STATS_END, stats_html)
    text = replace_marked_region(text, HOME_CONTENT_START, HOME_CONTENT_END, content_html)
    with tempfile.NamedTemporaryFile(
        mode="w",
        encoding="utf-8",
        prefix=".index-home-bootstrap-",
        suffix=".html",
        dir=str(index_path.parent),
        delete=False,
    ) as handle:
        temp_index = Path(handle.name)
        handle.write(text)
    temp_index.replace(index_path)
    return {
        "status": "success",
        "path": str(index_path),
        "sha256": sha256_file(index_path),
        "generated_at": home_payload.get("generatedAt"),
        "bytes": index_path.stat().st_size,
        "gzip_bytes": len(gzip.compress(index_path.read_bytes(), compresslevel=9, mtime=0)),
    }


def sync_site_index(*, payload_path: Path, index_path: Path) -> dict[str, object]:
    payload = json.loads(payload_path.read_text(encoding="utf-8"))
    index_payload = build_site_index(payload)
    index_path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(
        mode="w",
        encoding="utf-8",
        prefix=".site-index-",
        suffix=".json",
        dir=str(index_path.parent),
        delete=False,
    ) as handle:
        temp_index = Path(handle.name)
        json.dump(index_payload, handle, ensure_ascii=False, separators=(",", ":"))
    try:
        raw_bytes = temp_index.read_bytes()
        temp_index.replace(index_path)
    finally:
        if temp_index.exists():
            temp_index.unlink()
    route_indexes = build_route_indexes(index_payload, index_path.parent)
    return {
        "status": "success",
        "path": str(index_path),
        "sha256": sha256_file(index_path),
        "bytes": len(raw_bytes),
        "gzip_bytes": len(gzip.compress(raw_bytes, compresslevel=9, mtime=0)),
        "counts": {
            name: len(rows) for name, rows in index_payload["collections"].items()
        },
        "route_indexes": route_indexes,
    }


def sync_detail_shards(*, payload_path: Path, detail_root: Path) -> dict[str, object]:
    payload = json.loads(payload_path.read_text(encoding="utf-8"))
    collections = dict(payload.get("collections") or {})
    detail_root.parent.mkdir(parents=True, exist_ok=True)
    staging_root = Path(
        tempfile.mkdtemp(prefix=".details-staging-", dir=str(detail_root.parent))
    )
    entries: list[dict[str, object]] = []
    counts: dict[str, int] = {}
    try:
        for collection_name, detail_type in DETAIL_COLLECTION_TYPES.items():
            rows = list(collections.get(collection_name) or [])
            counts[detail_type] = len(rows)
            type_root = staging_root / detail_type
            type_root.mkdir(parents=True, exist_ok=True)
            for item in rows:
                item_id = str(item.get("id") or "").strip()
                if not item_id:
                    raise RuntimeError(f"{collection_name} detail item is missing id")
                filename = f"{quote(item_id, safe=URL_SAFE_FILENAME_CHARS)}.json"
                shard_path = type_root / filename
                shard = {
                    "schemaVersion": payload.get("schemaVersion"),
                    "generatedAt": payload.get("generatedAt"),
                    "type": detail_type,
                    "id": item_id,
                    "item": item,
                }
                shard_path.write_text(
                    json.dumps(shard, ensure_ascii=False, separators=(",", ":")),
                    encoding="utf-8",
                )
                entries.append(
                    {
                        "type": detail_type,
                        "id": item_id,
                        "path": f"details/{detail_type}/{filename}",
                        "bytes": shard_path.stat().st_size,
                        "sha256": sha256_file(shard_path),
                    }
                )

        backup_root = detail_root.with_name(f".{detail_root.name}-backup-{os.getpid()}")
        if backup_root.exists():
            shutil.rmtree(backup_root)
        if detail_root.exists():
            detail_root.replace(backup_root)
        staging_root.replace(detail_root)
        if backup_root.exists():
            shutil.rmtree(backup_root)

        manifest = {
            "schemaVersion": payload.get("schemaVersion"),
            "generatedAt": payload.get("generatedAt"),
            "count": len(entries),
            "counts": counts,
            "entries": entries,
        }
        manifest_path = detail_root.parent / "details-manifest.json"
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            prefix=".details-manifest-",
            suffix=".json",
            dir=str(manifest_path.parent),
            delete=False,
        ) as handle:
            temp_manifest = Path(handle.name)
            json.dump(manifest, handle, ensure_ascii=False, separators=(",", ":"))
        temp_manifest.replace(manifest_path)
        return {
            "status": "success",
            "root": str(detail_root),
            "manifest": str(manifest_path),
            "manifest_sha256": sha256_file(manifest_path),
            "count": len(entries),
            "counts": counts,
        }
    finally:
        if staging_root.exists():
            shutil.rmtree(staging_root)


def run_build(*, repo_root: Path, out_path: Path) -> None:
    command = [
        sys.executable,
        str(BUILD_SCRIPT),
        "--repo-root",
        str(repo_root),
        "--out",
        str(out_path),
    ]
    subprocess.run(command, check=True)


def summarize_payload(path: Path) -> dict[str, object]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    collections = payload.get("collections", {})
    counts = {
        name: len(rows) for name, rows in collections.items() if isinstance(rows, list)
    }
    news_meta = dict(payload.get("newsMeta") or {})
    if news_meta:
        counts["news"] = int(news_meta.get("totalCount", counts.get("news", 0)))
    return {
        "schema_version": payload.get("schemaVersion", ""),
        "counts": counts,
        "news_mirrored_count": int(news_meta.get("mirroredCount", len(collections.get("news", [])))),
        "relation_count": len(payload.get("relations", [])),
        "timeline_count": len(payload.get("timeline", [])),
        "build_id": dict(payload.get("buildMeta") or {}).get("buildId", ""),
        "source_digest": dict(payload.get("buildMeta") or {}).get("sourceDigest", ""),
    }


def validate_count_changes(*, before_path: Path, after_path: Path, max_drop_ratio: float) -> None:
    if not before_path.exists():
        return
    before = summarize_payload(before_path).get("counts", {})
    after = summarize_payload(after_path).get("counts", {})
    for name, old_value in dict(before).items():
        new_value = int(dict(after).get(name, 0))
        old_value = int(old_value)
        if old_value <= 0:
            continue
        drop_ratio = (old_value - new_value) / old_value
        if drop_ratio > max_drop_ratio:
            raise RuntimeError(
                f"count drop guard rejected {name}: {old_value} -> {new_value} "
                f"({drop_ratio:.1%} > {max_drop_ratio:.1%})"
            )


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Rebuild portal site-data.json from local KFC truth sources."
    )
    parser.add_argument("--repo-root", default="")
    parser.add_argument("--out", default=str(SITE_ROOT / "data" / "site-data.json"))
    parser.add_argument("--max-count-drop-ratio", type=float, default=0.05)
    parser.add_argument("--allow-count-drop", action="store_true")
    args = parser.parse_args()

    repo_root = Path(args.repo_root or str(find_repo_root())).expanduser().resolve()
    out_path = Path(args.out).expanduser().resolve()
    out_path.parent.mkdir(parents=True, exist_ok=True)

    before_exists = out_path.exists()
    before_sha = sha256_file(out_path) if before_exists else ""

    with tempfile.NamedTemporaryFile(
        prefix="site-data-", suffix=".json", dir=str(out_path.parent), delete=False
    ) as handle:
        temp_path = Path(handle.name)

    try:
        run_build(repo_root=repo_root, out_path=temp_path)
        validation = validate_portal_file(temp_path)
        after_sha = sha256_file(temp_path)
        summary = summarize_payload(temp_path)
        if not args.allow_count_drop:
            validate_count_changes(
                before_path=out_path,
                after_path=temp_path,
                max_drop_ratio=max(0.0, args.max_count_drop_ratio),
            )
        before_summary = summarize_payload(out_path) if before_exists else {}
        source_unchanged = bool(before_exists) and (
            before_summary.get("source_digest") == summary.get("source_digest")
        )
        if source_unchanged:
            after_sha = before_sha
        else:
            temp_path.replace(out_path)
    finally:
        if temp_path.exists():
            temp_path.unlink()

    detail_shards = sync_detail_shards(
        payload_path=out_path,
        detail_root=out_path.parent / "details",
    )
    site_index = sync_site_index(
        payload_path=out_path,
        index_path=out_path.parent / "site-index.json",
    )
    home_bootstrap = sync_home_bootstrap(
        index_path=out_path.parent.parent / "index.html",
        route_home_path=out_path.parent / "route-home.json",
    )

    result = {
        "status": "success",
        "generated_at": now_iso(),
        "repo_root": str(repo_root),
        "out": str(out_path),
        "replaced_existing": before_exists,
        "changed": before_sha != after_sha,
        "source_unchanged": source_unchanged,
        "before_sha256": before_sha,
        "after_sha256": after_sha,
        **summary,
        "validation": validation,
        "site_index": site_index,
        "home_bootstrap": home_bootstrap,
        "detail_shards": detail_shards,
    }
    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
