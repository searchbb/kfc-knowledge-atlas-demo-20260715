from __future__ import annotations

import argparse
import hashlib
import json
import re
import sqlite3
import subprocess
from dataclasses import dataclass
from datetime import datetime, timezone
from html import unescape
from pathlib import Path
from typing import Iterable
from urllib.parse import urlparse

import markdown
from portal_schema import PORTAL_SCHEMA_VERSION, schema_descriptor, validate_portal_payload


TOPIC_SECTION_RE = re.compile(r"^## TOPIC: (?P<title>.+)$", re.MULTILINE)
TOPIC_ID_RE = re.compile(r"^- topic_id:\s*(?P<value>.+)$", re.MULTILINE)
FIELD_RE = re.compile(r"^- (?P<key>[a-zA-Z0-9_]+):\s*(?P<value>.+)$", re.MULTILINE)
HEADER_RE = re.compile(r"^#\s+(?P<title>.+)$", re.MULTILINE)
ISSUE_HEADER_RE = re.compile(r"^# Issue Card:\s*(?P<title>.+)$", re.MULTILINE)
MERGED_HEADER_RE = re.compile(r"^# Issue Card:\s*(?P<title>.+)$", re.MULTILINE)
TOPIC_SHADOW_RE = re.compile(r"^## TOPIC_ID:\s*(?P<topic_id>.+)$", re.MULTILINE)
SHADOW_ISSUE_RE = re.compile(
    r"^- issue_card_id:\s*(?P<issue_id>[^|]+)\|\s*articles:\s*(?P<articles>\d+)\s*\|\s*question:\s*(?P<question>.+)$",
    re.MULTILINE,
)
FRONT_MATTER_RE = re.compile(r"^---\n(?P<body>.*?)\n---\n", re.DOTALL)
FRONT_MATTER_KV_RE = re.compile(r"^(?P<key>[A-Za-z0-9_]+):\s*(?P<value>.+)$")


@dataclass
class Topic:
    id: str
    title: str
    status: str
    issue_count_declared: int | None
    article_count: int | None
    last_updated: str | None
    issue_ids: list[str]
    active_issue_ids: list[str]
    related_card_ids: list[str]
    related_research_ids: list[str]


def first_nonempty(*values: str | None) -> str:
    for value in values:
        if value is None:
            continue
        text = str(value).strip()
        if text:
            return text
    return ""


def isoformat_from_mtime(path: Path) -> str:
    return datetime.fromtimestamp(path.stat().st_mtime, tz=timezone.utc).isoformat()


def relative_source_ref(path_value: str, repo_root: Path) -> str:
    path = Path(path_value)
    try:
        return path.resolve().relative_to(repo_root).as_posix()
    except (OSError, ValueError):
        return path.name


def sanitize_public_text(value: str, repo_root: Path) -> str:
    cleaned = value.replace(str(repo_root), "[repository]")
    return re.sub(r"/Users/[^\s<>\"']+", "[local-path]", cleaned)


def sanitize_public_payload(value, repo_root: Path):
    if isinstance(value, dict):
        return {key: sanitize_public_payload(item, repo_root) for key, item in value.items()}
    if isinstance(value, list):
        return [sanitize_public_payload(item, repo_root) for item in value]
    if isinstance(value, str):
        return sanitize_public_text(value, repo_root)
    return value


def repo_revision(repo_root: Path) -> str:
    result = subprocess.run(
        ["git", "rev-parse", "--short=12", "HEAD"],
        cwd=repo_root,
        text=True,
        capture_output=True,
        check=False,
    )
    return result.stdout.strip() or "unversioned"


def plain_text(html: str) -> str:
    text = re.sub(r"<[^>]+>", " ", html)
    return re.sub(r"\s+", " ", unescape(text)).strip()


def render_markdown(text: str) -> str:
    return markdown.markdown(
        text,
        extensions=["extra", "fenced_code", "tables", "sane_lists", "toc"],
        output_format="html5",
    )


def read_json(path: Path) -> dict:
    if not path.exists():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}
    return payload if isinstance(payload, dict) else {}


def section_body(text: str, heading: str) -> str:
    pattern = re.compile(
        rf"^##\s+{re.escape(heading)}\s*$" r"(?P<body>.*?)(?=^##\s+|\Z)",
        re.MULTILINE | re.DOTALL,
    )
    match = pattern.search(text)
    return match.group("body").strip() if match else ""


def parse_int(value: str | None) -> int | None:
    if value is None or value == "N/A":
        return None
    try:
        return int(value)
    except ValueError:
        return None


def parse_front_matter(raw: str) -> tuple[dict[str, str], str]:
    match = FRONT_MATTER_RE.match(raw)
    if not match:
        return {}, raw
    metadata: dict[str, str] = {}
    for line in match.group("body").splitlines():
        field = FRONT_MATTER_KV_RE.match(line.strip())
        if not field:
            continue
        value = field.group("value").strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
            value = value[1:-1]
        metadata[field.group("key")] = value
    return metadata, raw[match.end():]


def summarize_markdown(raw: str, *, limit: int = 320) -> str:
    _, body = parse_front_matter(raw)
    body = re.sub(r"^#.*$", " ", body, flags=re.MULTILINE)
    body = re.sub(r"^>.*$", " ", body, flags=re.MULTILINE)
    body = re.sub(r"!\[[^\]]*\]\([^)]+\)", " ", body)
    body = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", body)
    body = body.replace("`", " ")
    summary = re.sub(r"\s+", " ", body).strip()
    return summary[:limit]


def detect_source_id(*, metadata: dict[str, str], fallback_url: str = "") -> str:
    source_id = first_nonempty(metadata.get("source_id"))
    if source_id:
        return source_id
    source = first_nonempty(metadata.get("source"))
    if source.startswith("http://") or source.startswith("https://"):
        parsed = urlparse(source)
        return parsed.netloc or source
    if source:
        return source
    parsed = urlparse(fallback_url)
    return parsed.netloc or "local_article"


def parse_topic_registry(path: Path) -> list[Topic]:
    text = path.read_text(encoding="utf-8")
    matches = list(TOPIC_SECTION_RE.finditer(text))
    topics: list[Topic] = []

    for idx, match in enumerate(matches):
        start = match.start()
        end = matches[idx + 1].start() if idx + 1 < len(matches) else len(text)
        block = text[start:end]
        title = match.group("title").strip()
        fields = {m.group("key"): m.group("value").strip() for m in FIELD_RE.finditer(block)}
        issue_ids = re.findall(r"issue_card_id:\s*([a-zA-Z0-9_]+)", block)
        topics.append(
            Topic(
                id=fields.get("topic_id", title),
                title=title,
                status=fields.get("status", "unknown"),
                issue_count_declared=parse_int(fields.get("issue_count")),
                article_count=parse_int(fields.get("article_count")),
                last_updated=fields.get("last_updated"),
                issue_ids=issue_ids,
                active_issue_ids=[],
                related_card_ids=[],
                related_research_ids=[],
            )
        )
    return topics


def parse_shadow(path: Path) -> dict[str, list[dict[str, str | int]]]:
    text = path.read_text(encoding="utf-8")
    matches = list(TOPIC_SHADOW_RE.finditer(text))
    out: dict[str, list[dict[str, str | int]]] = {}

    for idx, match in enumerate(matches):
        start = match.start()
        end = matches[idx + 1].start() if idx + 1 < len(matches) else len(text)
        block = text[start:end]
        rows = []
        for row in SHADOW_ISSUE_RE.finditer(block):
            rows.append(
                {
                    "issue_id": row.group("issue_id").strip(),
                    "articles": int(row.group("articles")),
                    "question": row.group("question").strip(),
                }
            )
        out[match.group("topic_id").strip()] = rows
    return out


def parse_issue_markdown(path: Path) -> dict:
    raw = path.read_text(encoding="utf-8")
    title_match = ISSUE_HEADER_RE.search(raw)
    title = title_match.group("title").strip() if title_match else path.stem
    fields = {m.group("key"): m.group("value").strip() for m in FIELD_RE.finditer(raw)}
    question = section_body(raw, "Canonical Question").split("\n\n")[0].strip()
    html = render_markdown(raw)
    return {
        "id": fields.get("issue_card_id", path.stem),
        "type": "issue",
        "title": title,
        "topicId": fields.get("topic_id", path.parent.name),
        "status": fields.get("status", "unknown"),
        "sourceArticleCount": parse_int(fields.get("source_article_count")),
        "updatedAt": fields.get("updated_at"),
        "createdAt": fields.get("created_at"),
        "canonicalQuestion": question,
        "path": str(path),
        "mtime": isoformat_from_mtime(path),
        "html": html,
        "text": plain_text(html),
    }


def parse_merged_markdown(path: Path) -> dict:
    raw = path.read_text(encoding="utf-8")
    title_match = MERGED_HEADER_RE.search(raw)
    title = title_match.group("title").strip() if title_match else path.stem
    fields = {m.group("key"): m.group("value").strip() for m in FIELD_RE.finditer(raw)}
    question = section_body(raw, "Canonical Question").split("\n\n")[0].strip()
    html = render_markdown(raw)
    return {
        "id": fields.get("issue_card_id", path.stem),
        "type": "card",
        "title": title,
        "topicId": fields.get("topic_id"),
        "status": fields.get("status", "active"),
        "sourceArticleCount": parse_int(fields.get("source_article_count")),
        "updatedAt": fields.get("updated_at"),
        "createdAt": fields.get("created_at"),
        "canonicalQuestion": question,
        "path": str(path),
        "mtime": isoformat_from_mtime(path),
        "html": html,
        "text": plain_text(html),
    }


def parse_research_report(path: Path) -> dict:
    raw = path.read_text(encoding="utf-8")
    header = HEADER_RE.search(raw)
    title = header.group("title").strip() if header else path.parent.name
    html = render_markdown(raw)
    return {
        "id": path.parent.name,
        "type": "research",
        "title": title,
        "topicId": None,
        "status": "published",
        "updatedAt": None,
        "createdAt": None,
        "canonicalQuestion": "",
        "path": str(path),
        "mtime": isoformat_from_mtime(path),
        "html": html,
        "text": plain_text(html),
    }


def parse_article_directory(path: Path) -> dict:
    raw_path = path / "raw.md"
    raw = raw_path.read_text(encoding="utf-8")
    metadata, body = parse_front_matter(raw)
    meta_json = read_json(path / "meta.json")
    digest_meta = read_json(path / "digest_meta.json")
    issue_meta = read_json(path / "issue_card_meta.json")
    header = HEADER_RE.search(body)
    title = first_nonempty(
        metadata.get("title"),
        str(meta_json.get("title") or ""),
        str(digest_meta.get("title") or ""),
        header.group("title").strip() if header else "",
        path.name,
    )
    url = first_nonempty(
        metadata.get("url"),
        metadata.get("source_url"),
        str(meta_json.get("source_url") or ""),
    )
    source_id = detect_source_id(metadata=metadata, fallback_url=url)
    digest_status = str(digest_meta.get("status") or "").strip()
    issue_status = str(issue_meta.get("status") or "").strip()
    if digest_status == "success" and issue_status == "success":
        status = "digested"
    elif digest_status == "success":
        status = "digest_ready"
    else:
        status = first_nonempty(issue_status, digest_status, "raw")
    return {
        "id": path.name,
        "type": "article",
        "title": title,
        "sourceId": source_id,
        "status": status,
        "publishedAt": first_nonempty(
            metadata.get("published_at"),
            metadata.get("date"),
            metadata.get("created"),
            str(meta_json.get("prepared_at") or ""),
            str(digest_meta.get("created_at") or ""),
        ),
        "updatedAt": first_nonempty(
            str(issue_meta.get("created_at") or ""),
            str(digest_meta.get("created_at") or ""),
            str(meta_json.get("prepared_at") or ""),
            isoformat_from_mtime(raw_path),
        ),
        "summary": summarize_markdown(raw),
        "path": str(raw_path),
        "url": url,
    }


def parse_news_rows(*, repo_root: Path, article_ids: set[str]) -> list[dict]:
    db_path = repo_root / "data" / "news_library" / "news_library.sqlite3"
    query = """
        SELECT
            article_id,
            source_id,
            title_zh,
            title_original,
            title_en,
            canonical_url,
            published_at,
            first_seen_at,
            digest_status,
            digested_at,
            last_seen_at,
            summary_zh,
            summary_original,
            digest_result_summary
        FROM news_articles
        ORDER BY COALESCE(NULLIF(published_at, ''), first_seen_at) DESC, article_id
    """
    with sqlite3.connect(db_path) as connection:
        connection.row_factory = sqlite3.Row
        rows = connection.execute(query).fetchall()
    news_rows: list[dict] = []
    for row in rows:
        article_id = str(row["article_id"])
        news_rows.append(
            {
                "id": article_id,
                "type": "news",
                "title": first_nonempty(row["title_zh"], row["title_original"], row["title_en"], article_id),
                "sourceId": str(row["source_id"] or ""),
                "status": first_nonempty(row["digest_status"], "new"),
                "publishedAt": first_nonempty(row["published_at"], row["first_seen_at"]),
                "updatedAt": first_nonempty(row["digested_at"], row["last_seen_at"], row["first_seen_at"]),
                "summary": first_nonempty(row["summary_zh"], row["summary_original"], row["digest_result_summary"]),
                "articleId": article_id if article_id in article_ids else "",
                "url": str(row["canonical_url"] or ""),
            }
        )
    return news_rows


def research_candidates(base: Path) -> list[Path]:
    patterns = {
        "final_report.md",
        "report.md",
        "report_final.md",
        "report_v2_final.md",
        "agentarts_seminar_report_final.md",
    }
    return sorted(
        [path for path in base.rglob("*.md") if path.name in patterns],
        key=lambda item: item.as_posix(),
    )


def relate_assets(
    topics: list[Topic],
    issues: list[dict],
    cards: list[dict],
    research: list[dict],
    shadow: dict[str, list[dict[str, str | int]]],
) -> None:
    issue_map = {issue["id"]: issue for issue in issues}
    for topic in topics:
        if topic.id in shadow:
            topic.active_issue_ids = [row["issue_id"] for row in shadow[topic.id]]
        else:
            topic.active_issue_ids = [issue_id for issue_id in topic.issue_ids if issue_id in issue_map]

        terms = [topic.id, topic.title] + topic.issue_ids + topic.active_issue_ids
        normalized_terms = [term for term in terms if term]

        for card in cards:
            haystack = " ".join([card["id"], card["title"], card["text"][:4000]])
            if any(term in haystack for term in normalized_terms):
                topic.related_card_ids.append(card["id"])

        for item in research:
            haystack = " ".join([item["id"], item["title"], item["text"][:4000]])
            if any(term in haystack for term in normalized_terms):
                topic.related_research_ids.append(item["id"])

        topic.related_card_ids = sorted(set(topic.related_card_ids))
        topic.related_research_ids = sorted(set(topic.related_research_ids))


def sort_timeline(items: Iterable[dict]) -> list[dict]:
    return sorted(
        (
            {
                "id": item["id"],
                "type": item["type"],
                "title": item["title"],
                "topicId": item.get("topicId"),
                "updatedAt": item.get("updatedAt") or item["mtime"],
                "path": item["path"],
            }
            for item in items
        ),
        key=lambda item: item["updatedAt"] or "",
        reverse=True,
    )


def build_relations(
    topics: list[dict],
    issues: list[dict],
    cards: list[dict],
    research: list[dict],
    articles: list[dict],
    news: list[dict],
) -> list[dict]:
    relations: list[dict] = []
    seen: set[tuple[str, str, str, str, str]] = set()
    valid_ids = {
        "topic": {item["id"] for item in topics},
        "issue": {item["id"] for item in issues},
        "card": {item["id"] for item in cards},
        "research": {item["id"] for item in research},
        "article": {item["id"] for item in articles},
        "news": {item["id"] for item in news},
    }

    def add_relation(relation_type: str, from_type: str, from_id: str, to_type: str, to_id: str) -> None:
        if not from_id or not to_id:
            return
        if from_id not in valid_ids.get(from_type, set()) or to_id not in valid_ids.get(to_type, set()):
            return
        key = (relation_type, from_type, from_id, to_type, to_id)
        if key in seen:
            return
        seen.add(key)
        relations.append(
            {
                "id": f"{relation_type}:{from_id}:{to_id}",
                "type": relation_type,
                "fromType": from_type,
                "fromId": from_id,
                "toType": to_type,
                "toId": to_id,
            }
        )

    for topic in topics:
        issue_ids = {item["id"] for item in issues}
        for issue_id in topic["issueIds"]:
            if issue_id in issue_ids:
                add_relation("topic_issue_declared", "topic", topic["id"], "issue", issue_id)
        for issue_id in topic["activeIssueIds"]:
            if issue_id in issue_ids:
                add_relation("topic_issue_active", "topic", topic["id"], "issue", issue_id)
        for card_id in topic["relatedCardIds"]:
            add_relation("topic_card_related", "topic", topic["id"], "card", card_id)
        for research_id in topic["relatedResearchIds"]:
            add_relation("topic_research_related", "topic", topic["id"], "research", research_id)

    for issue in issues:
        add_relation("issue_topic_parent", "issue", issue["id"], "topic", issue.get("topicId") or "")
    for card in cards:
        add_relation("card_topic_parent", "card", card["id"], "topic", card.get("topicId") or "")
    for item in research:
        add_relation("research_topic_parent", "research", item["id"], "topic", item.get("topicId") or "")
    article_ids = {item["id"] for item in articles}
    for owner_type, items in (("issue", issues), ("card", cards), ("research", research)):
        for item in items:
            haystack = f"{item.get('id', '')} {item.get('text', '')}"
            for article_id in article_ids:
                if article_id in haystack:
                    add_relation(
                        f"{owner_type}_article_evidence",
                        owner_type,
                        item["id"],
                        "article",
                        article_id,
                    )
    for item in news:
        article_id = item.get("articleId") or ""
        if article_id in article_ids:
            add_relation("news_article_materialized", "news", item["id"], "article", article_id)

    return relations


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo-root", required=True)
    parser.add_argument("--out", required=True)
    args = parser.parse_args()

    repo_root = Path(args.repo_root).resolve()
    out_path = Path(args.out).resolve()
    index_root = repo_root / "data/semantic_pipeline_v2/index"
    research_root = repo_root / "data/semantic_pipeline_v2/research_packs"
    article_root = repo_root / "data/semantic_pipeline_v2/articles"

    topics = parse_topic_registry(index_root / "topic_registry.md")
    shadow = parse_shadow(index_root / "registry_shadow_active_cards.md")

    issue_files = sorted(
        path
        for path in (index_root / "issue_cards").rglob("*.md")
        if ".bak." not in path.name
    )
    issues = [parse_issue_markdown(path) for path in issue_files]

    merged_files = sorted((index_root / "merged_cards").glob("*.md"))
    cards = [parse_merged_markdown(path) for path in merged_files]

    research_files = research_candidates(research_root)
    research = [parse_research_report(path) for path in research_files]
    research_seen: set[str] = set()
    for item, source_path in zip(research, research_files):
        if item["id"] in research_seen:
            item["id"] = f"{item['id']}__{source_path.stem}"
        research_seen.add(item["id"])
    article_dirs = sorted(path for path in article_root.iterdir() if path.is_dir())
    articles = [parse_article_directory(path) for path in article_dirs]
    news = parse_news_rows(repo_root=repo_root, article_ids={item["id"] for item in articles})

    # Public output keeps only repository-relative references. Absolute local paths
    # and the workstation root must never be exposed by the public portal.
    for collection in (issues, cards, research, articles):
        for item in collection:
            if item.get("path"):
                item["path"] = relative_source_ref(str(item["path"]), repo_root)

    relate_assets(topics, issues, cards, research, shadow)

    topic_rows = [
        {
            "id": topic.id,
            "title": topic.title,
            "status": topic.status,
            "issueCountDeclared": topic.issue_count_declared,
            "articleCount": topic.article_count,
            "lastUpdated": topic.last_updated,
            "issueIds": topic.issue_ids,
            "activeIssueIds": topic.active_issue_ids,
            "relatedCardIds": topic.related_card_ids,
            "relatedResearchIds": topic.related_research_ids,
        }
        for topic in topics
    ]

    active_issues = sum(1 for issue in issues if issue["status"] == "active")
    provisional_issues = sum(1 for issue in issues if issue["status"] == "provisional")
    latest_mtime = max(
        [item.get("updatedAt") or item["mtime"] for item in issues + cards + research]
        + [item.get("updatedAt") or "" for item in articles]
        + [item.get("updatedAt") or "" for item in news],
        default=datetime.now(tz=timezone.utc).isoformat(),
    )
    article_rows = articles
    news_rows = news
    relations = build_relations(topic_rows, issues, cards, research, article_rows, news_rows)
    timeline = sort_timeline(
        [
            *issues,
            *cards,
            *research,
            *[
                {
                    "id": item["id"],
                    "type": item["type"],
                    "title": item["title"],
                    "topicId": None,
                    "updatedAt": item["updatedAt"],
                    "path": item["path"],
                }
                for item in article_rows
            ],
            *[
                {
                    "id": item["id"],
                    "type": item["type"],
                    "title": item["title"],
                    "topicId": None,
                    "updatedAt": item["updatedAt"],
                    "path": "data/news_library/news_library.sqlite3",
                }
                for item in news_rows
            ],
        ]
    )[:360]

    source_fingerprint = {
        "topics": [(item["id"], item.get("lastUpdated")) for item in topic_rows],
        "issues": [(item["id"], item.get("updatedAt") or item.get("mtime")) for item in issues],
        "cards": [(item["id"], item.get("updatedAt") or item.get("mtime")) for item in cards],
        "research": [(item["id"], item.get("mtime")) for item in research],
        "articles": [(item["id"], item.get("updatedAt")) for item in article_rows],
        "news": [(item["id"], item.get("updatedAt"), item.get("status")) for item in news_rows],
    }
    source_digest = hashlib.sha256(
        json.dumps(source_fingerprint, ensure_ascii=False, sort_keys=True).encode("utf-8")
    ).hexdigest()

    payload = {
        "schemaVersion": PORTAL_SCHEMA_VERSION,
        "generatedAt": datetime.now(tz=timezone.utc).isoformat(),
        "schema": schema_descriptor(),
        "buildMeta": {
            "buildId": source_digest[:16],
            "sourceDigest": source_digest,
            "sourceRevision": repo_revision(repo_root),
            "generatorVersion": "portal-build-v2",
            "generator": "site-demo/scripts/build_site_data.py",
            "sourceRoots": {
                "index": "data/semantic_pipeline_v2/index",
                "research": "data/semantic_pipeline_v2/research_packs",
                "articles": "data/semantic_pipeline_v2/articles",
                "news_db": "data/news_library/news_library.sqlite3",
            },
            "notes": [
                "Task 01 fixes the unified portal schema and validates the build output against it.",
                "Task 02 wires article directories and the news library database into first-class portal collections.",
            ],
        },
        "stats": {
            "topics": len(topic_rows),
            "issues": len(issues),
            "cards": len(cards),
            "research": len(research),
            "articles": len(article_rows),
            "news": len(news_rows),
            "relations": len(relations),
            "activeIssues": active_issues,
            "provisionalIssues": provisional_issues,
            "latestUpdate": latest_mtime,
        },
        "collections": {
            "topics": topic_rows,
            "issues": issues,
            "cards": cards,
            "research": research,
            "articles": article_rows,
            "news": news_rows,
        },
        "topics": topic_rows,
        "issues": issues,
        "cards": cards,
        "research": research,
        "articles": article_rows,
        "news": news_rows,
        "relations": relations,
        "timeline": timeline,
    }
    payload = sanitize_public_payload(payload, repo_root)
    validate_portal_payload(payload)

    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


if __name__ == "__main__":
    main()
