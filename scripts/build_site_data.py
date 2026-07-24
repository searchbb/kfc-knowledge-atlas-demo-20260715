from __future__ import annotations

import argparse
import hashlib
import json
import re
import shutil
import sqlite3
import subprocess
from dataclasses import dataclass
from datetime import datetime, timezone
from difflib import SequenceMatcher
from html import escape, unescape
from pathlib import Path
from typing import Iterable
from urllib.parse import urlparse

import markdown
from portal_schema import PORTAL_SCHEMA_VERSION, schema_descriptor, validate_portal_payload
from public_release_policy import partition_public_items
from research_publication import VERIFIED_ADMISSION, validate_verified_manifest_row


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
MARKDOWN_IMAGE_RE = re.compile(r"!\[(?P<alt>[^\]]*)\]\((?P<target>[^)]+)\)")
SITE_ROOT = Path(__file__).resolve().parents[1]
RESEARCH_MANIFEST = Path(__file__).resolve().with_name("research_publication_manifest.json")

CARD_HEADING_LABELS = {
    "Metadata": "基本信息",
    "Canonical Question": "核心问题",
    "Why It Matters": "为什么重要",
    "Current Viewpoints": "当前观点",
    "Key Evidence": "关键证据",
    "Mechanisms": "作用机制",
    "Risks / Uncertainties": "风险与不确定性",
    "Risks & Uncertainties": "风险与不确定性",
    "Related Articles": "相关文章",
    "Archived / Replaced": "已归档或替换",
    "Retire Record": "退役记录",
    "Former Canonical Question": "原核心问题",
    "Why This Was Migrated": "迁移原因",
    "Capsule Role": "卡片作用",
    "Supporting Evidence Viewpoints": "补充证据观点",
    "Mechanism Notes": "机制说明",
    "Migration Notes": "迁移说明",
    "Future Merge Candidates": "后续合并候选",
    "Supporting Evidence Archive": "补充证据档案",
    "Briefing-Derived Pending Mechanisms": "简报提取的待验证机制",
    "Deferred Recovery Rule": "延后恢复规则",
    "Governance Note": "治理说明",
    "Status": "状态",
    "Summary": "摘要",
    "Stance": "判断立场",
    "Evidence": "证据",
    "Viewpoints": "观点",
    "Quarantine Note": "隔离说明",
    "Retired Incomplete Audit Capsule": "已退役的不完整审计档案",
    "Retired No-Evidence Audit Capsule": "已退役的无证据审计档案",
    "Department Strategy Relevance": "与部门策略的关联",
    "Recovery Status": "恢复状态",
    "Linked Article IDs": "关联文章编号",
    "Original Truncated Fragment": "原始截断片段",
    "Provisional Triage Note": "临时分流说明",
}
CARD_FIELD_LABELS = {
    "issue_card_id": "卡片编号",
    "topic_id": "所属专题",
    "status": "状态",
    "created_at": "创建时间",
    "updated_at": "更新时间",
    "source_article_count": "参考文章数量",
    "last_update_article_id": "最近更新文章",
    "representative_claims": "代表性主张",
    "claim": "主张",
    "article_id": "文章编号",
    "evidence_refs": "证据编号",
    "why_kept": "保留理由",
    "evidence_ref": "证据编号",
    "excerpt": "证据摘录",
    "why_important": "重要性",
    "title": "标题",
    "chain": "作用链路",
    "evidence": "证据",
    "articles": "相关文章",
    "role": "材料作用",
    "old_claim": "原主张",
    "replaced_by": "替代内容",
    "reason": "原因",
    "retired_at": "退役时间",
    "merge_target": "合并目标",
}
CARD_VALUE_LABELS = {
    "active": "持续关注",
    "provisional": "观察中",
    "retired": "已退役",
    "retired_merged": "已合并退役",
    "primary": "主要材料",
    "supporting": "补充材料",
    "none": "无",
}


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


def localize_analysis_card(raw: str) -> str:
    """Translate the public rendering without mutating canonical Markdown."""
    localized = re.sub(r"^#\s+Issue Card:\s*", "# 分析卡片：", raw, flags=re.MULTILINE)
    localized = re.sub(r"^#\s+Evidence Capsule:\s*", "# 分析卡片（证据档案）：", localized, flags=re.MULTILINE | re.IGNORECASE)
    localized = re.sub(r"^#\s+Incomplete Issue Card Capsule:\s*", "# 分析卡片（待完善）：", localized, flags=re.MULTILINE | re.IGNORECASE)
    for source, label in CARD_HEADING_LABELS.items():
        localized = re.sub(
            rf"^(##\s+){re.escape(source)}\s*$",
            rf"\1{label}",
            localized,
            flags=re.MULTILINE | re.IGNORECASE,
        )
    localized = re.sub(
        r"^(###\s+)Viewpoint\s+(\d+)\s*:\s*",
        r"\1观点 \2：",
        localized,
        flags=re.MULTILINE | re.IGNORECASE,
    )
    localized = re.sub(
        r"^(###\s+)Viewpoint\s*:\s*",
        r"\1观点：",
        localized,
        flags=re.MULTILINE | re.IGNORECASE,
    )
    field_pattern = re.compile(
        r"^(?P<indent>\s*)(?P<bullet>-\s+)?(?P<key>"
        + "|".join(re.escape(key) for key in sorted(CARD_FIELD_LABELS, key=len, reverse=True))
        + r")\s*:\s*(?P<value>.*)$",
        re.MULTILINE | re.IGNORECASE,
    )

    def replace_field(match: re.Match[str]) -> str:
        key = match.group("key").lower()
        value = match.group("value").strip()
        value = CARD_VALUE_LABELS.get(value.lower(), value)
        label = CARD_FIELD_LABELS[key]
        return f"{match.group('indent')}{match.group('bullet') or ''}**{label}：** {value}".rstrip()

    return field_pattern.sub(replace_field, localized)


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
    body = re.sub(
        r"^(?:\*\*)?(?:Date|Status|Version|Research Report Status|Generated|Method|Scope)(?:\*\*)?\s*[:：].*$",
        " ",
        body,
        flags=re.MULTILINE | re.IGNORECASE,
    )
    body = re.sub(r"!\[[^\]]*\]\([^)]+\)", " ", body)
    body = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", body)
    body = re.sub(r"[*_~`]+", " ", body)
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
    html = render_markdown(localize_analysis_card(raw))
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
    html = render_markdown(localize_analysis_card(raw))
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


def stage_research_images(raw: str, *, path: Path, report_id: str, stage_root: Path) -> str:
    def replace(match: re.Match[str]) -> str:
        target = match.group("target").strip()
        if target.startswith("<") and target.endswith(">"):
            target = target[1:-1]
        parsed = urlparse(target)
        if parsed.scheme or target.startswith(("#", "/")):
            return match.group(0)
        source = (path.parent / target).resolve()
        if not source.is_file():
            return match.group(0)
        destination = stage_root / report_id / source.name
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, destination)
        public_target = f"./assets/research/{report_id}/{source.name}"
        return f"![{match.group('alt')}]({public_target})"

    return MARKDOWN_IMAGE_RE.sub(replace, raw)


def parse_research_report(
    path: Path,
    *,
    report_id: str,
    category: str,
    asset_stage_root: Path,
    published_at: str = "",
) -> dict:
    raw = path.read_text(encoding="utf-8")
    raw = stage_research_images(
        raw,
        path=path,
        report_id=report_id,
        stage_root=asset_stage_root,
    )
    header = HEADER_RE.search(raw)
    title = header.group("title").strip() if header else path.parent.name
    title = re.sub(r"^Research Report\s*[:：]\s*", "", title, flags=re.IGNORECASE)
    html = render_markdown(raw)
    return {
        "id": report_id,
        "type": "research",
        "title": title,
        "category": category,
        "topicId": None,
        "status": "published",
        "updatedAt": published_at or None,
        "createdAt": published_at or None,
        "canonicalQuestion": "",
        "path": str(path),
        "mtime": isoformat_from_mtime(path),
        "html": html,
        "text": plain_text(html),
        "summary": summarize_markdown(raw),
        "diagramCount": len(re.findall(r"^```mermaid\s*$", raw, re.MULTILINE | re.IGNORECASE)),
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


def parse_news_rows(*, repo_root: Path, article_ids: set[str], limit: int) -> tuple[list[dict], int]:
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
        WHERE published_at <> ''
        ORDER BY published_at DESC, article_id
        LIMIT ?
    """
    with sqlite3.connect(db_path) as connection:
        connection.row_factory = sqlite3.Row
        total_count = int(connection.execute("SELECT COUNT(*) FROM news_articles").fetchone()[0])
        rows = connection.execute(query, (max(1, limit),)).fetchall()
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
    return news_rows, total_count


def _json_value(value: str, default: object) -> object:
    try:
        return json.loads(value) if value else default
    except json.JSONDecodeError:
        return default


STRATEGIC_OBJECT_TERMS = (
    "营收",
    "收入",
    "利润",
    "毛利",
    "成本",
    "价格",
    "客户",
    "用户",
    "订单",
    "积压",
    "商业化",
    "资本开支",
    "算力",
    "token",
    "吞吐",
    "产能",
    "市场份额",
    "合作",
    "伙伴",
    "收购",
    "监管",
    "治理",
    "安全事件",
    "revenue",
    "margin",
    "cost",
    "customer",
    "backlog",
    "commercial",
    "capex",
    "partnership",
    "acquisition",
)
MICRO_OBJECT_TERMS = (
    "语言支持",
    "language support",
    "连接器",
    "connector",
    "菜单",
    "menu",
    "套餐可用",
    "套餐开放",
    "plan availability",
    "语音模式",
    "voice mode",
    "语音合成",
    "text-to-speech",
    "tts",
    "gmail",
    "slack",
    "benchmark",
    "基准",
    "榜单",
    "排行榜",
    "字体",
    "font",
    "菜单路径",
    "点击路径",
    "按住说话",
    "参数规模",
    "parameter count",
    "fp32",
    "fp16",
    "fp8",
    "fp4",
    "数据精度",
    "显存规模",
    "单实例",
    "gb/s",
    "health 集成",
    "health integration",
    "集成预计",
    "面向客户开放",
    "首轮 token",
    "首轮token",
    "单轮 token",
    "单轮token",
    "单次 token",
    "单次token",
    "first round token",
    "first-round token",
    "评估流水线",
    "evaluation pipeline",
)
STRATEGIC_BLOCK_WEIGHTS = {
    "unit_economics": 60,
    "business_model": 48,
    "resource_control": 44,
    "strategic_judgment": 42,
    "relationships": 34,
    "key_metrics": 30,
    "control_points": 28,
    "recent_updates": 8,
}
STRATEGIC_ENTITY_TERMS = (
    "openai",
    "anthropic",
    "amd",
    "nvidia",
    "英伟达",
    "阿里云",
    "alibaba",
    "google",
    "谷歌",
    "microsoft",
    "微软",
    "华为",
    "huawei",
    "amazon",
    "亚马逊",
    "真武",
    "qwen",
)
STRATEGIC_THEME_TERMS = {
    "acquisition": ("收购", "acquire", "acquisition"),
    "partnership": ("合作", "伙伴", "partnership", "agreement", "协议"),
    "compute": (
        "算力",
        "gpu",
        "芯片",
        "chip",
        "数据中心",
        "infrastructure",
        "基础设施",
        "超节点",
        "gw",
        "电力",
    ),
    "finance": (
        "营收",
        "收入",
        "利润",
        "毛利",
        "成本",
        "投资",
        "revenue",
        "margin",
        "cost",
        "billion",
        "亿美元",
    ),
    "adoption": ("客户", "用户", "部署", "customer", "user", "adopt", "deploy"),
    "product": ("发布", "推出", "上线", "launch", "release"),
    "governance": ("监管", "治理", "安全", "regulation", "governance", "security"),
}


def canonical_update_score(item: dict) -> int:
    text = f"{item.get('fact_subject') or ''} {item.get('statement') or ''}".lower()
    return (
        STRATEGIC_BLOCK_WEIGHTS.get(str(item.get("block_id") or ""), 0)
        + (35 if str(item.get("asset_role") or "") == "strategic_event" else 0)
        + (28 if any(term in text for term in STRATEGIC_OBJECT_TERMS) else 0)
        + (10 if any(char.isdigit() for char in text) else 0)
        - (100 if any(term in text for term in MICRO_OBJECT_TERMS) else 0)
    )


def canonical_update_signature(item: dict) -> tuple[tuple[str, ...], tuple[str, ...]]:
    text = f"{item.get('fact_subject') or ''} {item.get('statement') or ''}".lower()
    entities = tuple(sorted(term for term in STRATEGIC_ENTITY_TERMS if term in text))
    themes = tuple(
        sorted(
            theme
            for theme, terms in STRATEGIC_THEME_TERMS.items()
            if any(term in text for term in terms)
        )
    )
    return entities, themes


def select_strategic_object_updates(
    updates: list[dict],
    *,
    limit: int = 3,
    object_name: str = "",
    object_aliases: list[str] | None = None,
    object_kind: str = "",
) -> list[dict]:
    selected: list[dict] = []
    normalized: list[str] = []
    signatures: set[tuple[tuple[str, ...], tuple[str, ...]]] = set()
    ranked = sorted(
        updates,
        key=lambda item: (
            canonical_update_score(item),
            str(item.get("published_at") or ""),
            str(item.get("fact_id") or ""),
        ),
        reverse=True,
    )
    for item in ranked:
        if canonical_update_score(item) < 55:
            continue
        statement_text = str(item.get("statement") or "")
        lowered = statement_text.lower()
        if object_kind == "company":
            markers = [
                marker
                for marker in {
                    str(object_name or "").lower(),
                    *(str(alias or "").lower() for alias in (object_aliases or [])),
                }
                if len(marker) >= 3
            ]
            positions = [
                lowered.find(marker)
                for marker in markers
                if lowered.find(marker) >= 0
            ]
            if not positions:
                continue
            prefix = lowered[: min(positions)]
            if (
                min(positions) > 60
                or prefix.count("、") >= 2
                or prefix.count(",") >= 2
            ):
                continue
        signature = canonical_update_signature(item)
        if (
            "acquisition" in signature[1]
            and any("acquisition" in prior[1] for prior in signatures)
        ):
            continue
        if signature[1] and signature in signatures:
            continue
        statement = re.sub(r"\s+", "", lowered)
        if not statement:
            continue
        if any(
            SequenceMatcher(None, statement, prior).ratio() >= 0.72
            for prior in normalized
        ):
            continue
        selected.append(item)
        normalized.append(statement)
        if signature[1]:
            signatures.add(signature)
        if len(selected) >= limit:
            break
    return selected


def parse_canonical_research_objects(*, repo_root: Path) -> list[dict]:
    projection_path = (
        repo_root
        / "data"
        / "semantic_pipeline_v2"
        / "research_assets"
        / "projections"
        / "api_read_model.json"
    )
    if not projection_path.exists():
        return []
    payload = json.loads(projection_path.read_text(encoding="utf-8"))
    evidence_by_id: dict[str, dict] = {}
    evidence_db = (
        repo_root
        / "data"
        / "semantic_pipeline_v2"
        / "loop_engineering"
        / "news_value_research_cards.sqlite3"
    )
    if evidence_db.exists():
        with sqlite3.connect(f"file:{evidence_db}?mode=ro", uri=True) as connection:
            connection.row_factory = sqlite3.Row
            evidence_by_id = {
                str(row["evidence_id"]): dict(row)
                for row in connection.execute(
                    """
                    SELECT evidence_id, source_name, source_grade, source_url,
                           published_at, source_quote, locator, article_id,
                           verification_status
                    FROM evidence_cards
                    """
                ).fetchall()
            }
    result: list[dict] = []
    for object_id, profile in sorted(dict(payload.get("profiles") or {}).items()):
        object_data = dict((profile or {}).get("object") or {})
        updates_24h = select_strategic_object_updates(
            list(object_data.get("updates_24h") or []),
            limit=3,
            object_name=str(object_data.get("name") or ""),
            object_aliases=[
                str(item)
                for item in object_data.get("aliases") or []
                if str(item)
            ],
            object_kind=str(object_data.get("kind") or ""),
        )
        updates = [
            {
                "update_id": str(item.get("fact_id") or ""),
                "research_object_id": object_id,
                "event": str(item.get("statement") or ""),
                "event_date": str(item.get("published_at") or ""),
                "review_status": "fact_confirmed",
                "fact_id": str(item.get("fact_id") or ""),
                "evidence_id": str(item.get("evidence_id") or ""),
                "evidence": {
                    key: evidence_by_id.get(
                        str(item.get("evidence_id") or ""), {}
                    ).get(key, "")
                    for key in (
                        "source_name",
                        "source_grade",
                        "source_url",
                        "published_at",
                        "source_quote",
                        "locator",
                        "article_id",
                        "verification_status",
                    )
                },
            }
            for item in updates_24h
        ]
        update_html = "".join(
            (
                "<section class='value-change'>"
                f"<h3>{escape(str(item.get('statement') or '研究对象更新'))}</h3>"
                f"<p><strong>记录时间：</strong>{escape(str(item.get('published_at') or ''))}</p>"
                f"<p><strong>证据：</strong><a href='{escape(str(evidence_by_id.get(str(item.get('evidence_id') or ''), {}).get('source_url') or ''))}' "
                "target='_blank' rel='noreferrer'>"
                f"{escape(str(evidence_by_id.get(str(item.get('evidence_id') or ''), {}).get('source_name') or '公开来源'))} ↗</a></p>"
                "</section>"
            )
            for item in updates_24h
        )
        result.append(
            {
                "id": object_id,
                "type": "object",
                "title": str(object_data.get("name") or object_id),
                "status": str(object_data.get("status") or "active"),
                "category": str(object_data.get("kind") or "研究对象"),
                "summary": str(object_data.get("description") or ""),
                "updatedAt": first_nonempty(
                    str(object_data.get("latest_update_at") or ""),
                    str(object_data.get("updated_at") or ""),
                ),
                "createdAt": "",
                "objectType": str(object_data.get("kind") or ""),
                "businessArchetype": str(
                    object_data.get("business_archetype") or ""
                ),
                "attentionLevel": str(object_data.get("attention_level") or ""),
                "strategicPosition": str(
                    object_data.get("strategic_position") or ""
                ),
                "strategicThesis": "",
                "updates": updates,
                "facts": [
                    {
                        **item,
                        "source_url": str(
                            evidence_by_id.get(
                                str(item.get("evidence_id") or ""), {}
                            ).get("source_url")
                            or ""
                        ),
                        "status": "confirmed",
                    }
                    for item in updates_24h
                ],
                "factCount": int(object_data.get("fact_count") or 0),
                "html": (
                    f"<p>已积累 {int(object_data.get('fact_count') or 0)} 条可追溯记录；"
                    "以下仅展示最近24小时中最值得战略关注的更新。</p>"
                    + (update_html or "<p>尚无最近24小时正式更新记录。</p>")
                ),
            }
        )
    return result


def parse_research_objects(*, repo_root: Path) -> list[dict]:
    canonical_objects = parse_canonical_research_objects(repo_root=repo_root)
    db_path = (
        repo_root
        / "data"
        / "semantic_pipeline_v2"
        / "loop_engineering"
        / "news_value_research_cards.sqlite3"
    )
    if not db_path.exists():
        return canonical_objects
    with sqlite3.connect(f"file:{db_path}?mode=ro", uri=True) as connection:
        connection.row_factory = sqlite3.Row
        cards = connection.execute(
            """
            SELECT research_object_id, object_type, canonical_name, scope, category,
                   business_archetype, description, strategic_thesis, status,
                   attention_level, strategic_position, created_at, updated_at
            FROM research_cards
            ORDER BY datetime(updated_at) DESC, canonical_name
            """
        ).fetchall()
        updates = connection.execute(
            """
            SELECT update_id, research_object_id, event, event_date, impact_type,
                   before_state, after_state, direction, importance, review_status,
                   fact_id, evidence_id, created_at
            FROM research_updates
            WHERE review_status IN ('approved', 'fact_confirmed')
            ORDER BY datetime(created_at) DESC, update_id
            """
        ).fetchall()
        facts = connection.execute(
            """
            SELECT fact_id, research_object_id, fact_category, fact_subject, statement,
                   value_json, unit, currency, event_time, effective_period, published_at,
                   source_grade, source_url, status, version, is_current, created_at
            FROM fact_updates
            WHERE is_current=1
            ORDER BY datetime(created_at) DESC, fact_id
            """
        ).fetchall()
        evidence = {
            str(row["evidence_id"]): dict(row)
            for row in connection.execute(
                """
                SELECT evidence_id, source_type, source_name, source_grade, source_url,
                       published_at, source_quote, locator, article_id, verification_status
                FROM evidence_cards
                """
            ).fetchall()
        }
    updates_by_object: dict[str, list[dict]] = {}
    for row in updates:
        item = dict(row)
        evidence_item = evidence.get(str(item.get("evidence_id") or ""), {})
        item["evidence"] = {
            key: evidence_item.get(key, "")
            for key in (
                "source_name",
                "source_grade",
                "source_url",
                "published_at",
                "source_quote",
                "locator",
                "article_id",
                "verification_status",
            )
        }
        updates_by_object.setdefault(str(row["research_object_id"]), []).append(item)
    facts_by_object: dict[str, list[dict]] = {}
    for row in facts:
        item = dict(row)
        item["value"] = _json_value(str(item.pop("value_json") or ""), {})
        facts_by_object.setdefault(str(row["research_object_id"]), []).append(item)

    result: list[dict] = []
    for row in cards:
        object_id = str(row["research_object_id"])
        object_updates = updates_by_object.get(object_id, [])
        object_facts = facts_by_object.get(object_id, [])
        latest_update = first_nonempty(
            str(object_updates[0].get("created_at") or "") if object_updates else "",
            str(row["updated_at"] or ""),
        )
        update_html = "".join(
            (
                "<section class='value-change'>"
                f"<h3>{escape(str(item.get('event') or '研究对象更新'))}</h3>"
                f"<p><strong>变化方向：</strong>{escape(str(item.get('direction') or ''))}"
                f" · <strong>重要性：</strong>{int(item.get('importance') or 0)}</p>"
                f"<p><strong>原状态：</strong>{escape(str(item.get('before_state') or '此前未记录'))}</p>"
                f"<p><strong>新状态：</strong><mark>{escape(str(item.get('after_state') or ''))}</mark></p>"
                f"<p><strong>证据：</strong><a href='{escape(str((item.get('evidence') or {}).get('source_url') or ''))}' "
                "target='_blank' rel='noreferrer'>"
                f"{escape(str((item.get('evidence') or {}).get('source_name') or '公开来源'))} ↗</a></p>"
                "</section>"
            )
            for item in object_updates[:20]
        )
        result.append(
            {
                "id": object_id,
                "type": "object",
                "title": str(row["canonical_name"]),
                "status": str(row["status"] or "tracking"),
                "category": first_nonempty(str(row["category"] or ""), str(row["object_type"] or "")),
                "summary": first_nonempty(
                    str(row["description"] or ""),
                    str(row["strategic_thesis"] or ""),
                    str(row["scope"] or ""),
                ),
                "updatedAt": latest_update,
                "createdAt": str(row["created_at"] or ""),
                "objectType": str(row["object_type"] or ""),
                "businessArchetype": str(row["business_archetype"] or ""),
                "attentionLevel": str(row["attention_level"] or ""),
                "strategicPosition": str(row["strategic_position"] or ""),
                "strategicThesis": str(row["strategic_thesis"] or ""),
                "updates": object_updates,
                "facts": object_facts,
                "html": update_html or "<p>尚无正式更新记录。</p>",
            }
        )
    canonical_ids = {str(item["id"]) for item in canonical_objects}
    return [
        *[item for item in result if str(item["id"]) not in canonical_ids],
        *canonical_objects,
    ]


def parse_strategic_signals(*, repo_root: Path) -> list[dict]:
    db_path = (
        repo_root
        / "data"
        / "semantic_pipeline_v2"
        / "loop_engineering"
        / "news_value_signal_registry.sqlite3"
    )
    if not db_path.exists():
        return []
    with sqlite3.connect(f"file:{db_path}?mode=ro", uri=True) as connection:
        connection.row_factory = sqlite3.Row
        rows = connection.execute(
            """
            SELECT signal_id, hypothesis_id, hypothesis_title, delta_direction,
                   prior_view, new_evidence, updated_view, counterevidence_or_limit,
                   follow_up_question, confidence, source_grade, source_url,
                   source_article_ids_json, evidence_refs_json, review_reason,
                   signal_date, created_at, updated_at
            FROM news_value_signal_registry
            ORDER BY datetime(created_at) DESC, signal_id
            """
        ).fetchall()
    result: list[dict] = []
    for row in rows:
        item = dict(row)
        signal_id = str(item["signal_id"])
        source_url = str(item["source_url"] or "")
        body = (
            "<section class='value-change signal-change'>"
            f"<p><strong>变化方向：</strong>{escape(str(item['delta_direction']))}"
            f" · <strong>置信度：</strong>{float(item['confidence']):.0%}</p>"
            f"<h3>原判断</h3><p>{escape(str(item['prior_view']))}</p>"
            f"<h3>新判断</h3><p><mark>{escape(str(item['updated_view']))}</mark></p>"
            f"<h3>新增证据</h3><p>{escape(str(item['new_evidence']))}</p>"
            f"<h3>限制与反证</h3><p>{escape(str(item['counterevidence_or_limit']))}</p>"
            f"<h3>后续问题</h3><p>{escape(str(item['follow_up_question']))}</p>"
            f"<p><a href='{escape(source_url)}' target='_blank' rel='noreferrer'>查看公开来源 ↗</a></p>"
            "</section>"
        )
        result.append(
            {
                "id": signal_id,
                "type": "signal",
                "title": str(item["hypothesis_title"]),
                "status": "published",
                "summary": str(item["updated_view"]),
                "updatedAt": first_nonempty(str(item["updated_at"] or ""), str(item["created_at"] or "")),
                "createdAt": str(item["created_at"] or ""),
                "hypothesisId": str(item["hypothesis_id"]),
                "deltaDirection": str(item["delta_direction"]),
                "priorView": str(item["prior_view"]),
                "newEvidence": str(item["new_evidence"]),
                "updatedView": str(item["updated_view"]),
                "counterevidenceOrLimit": str(item["counterevidence_or_limit"]),
                "followUpQuestion": str(item["follow_up_question"]),
                "confidence": float(item["confidence"]),
                "sourceGrade": str(item["source_grade"]),
                "sourceId": urlparse(source_url).netloc.removeprefix("www."),
                "url": source_url,
                "sourceArticleIds": _json_value(str(item["source_article_ids_json"] or ""), []),
                "evidenceRefs": _json_value(str(item["evidence_refs_json"] or ""), []),
                "reviewReason": str(item["review_reason"]),
                "signalDate": str(item["signal_date"]),
                "html": body,
            }
        )
    return result


def research_candidates(
    repo_root: Path,
    manifest_path: Path = RESEARCH_MANIFEST,
) -> list[tuple[dict[str, str], Path]]:
    repo_root = repo_root.expanduser().resolve()
    manifest = read_json(manifest_path)
    rows = manifest.get("reports") or []
    if not isinstance(rows, list) or not rows:
        raise ValueError(f"research publication manifest is empty: {manifest_path}")
    candidates: list[tuple[dict[str, str], Path]] = []
    seen_ids: set[str] = set()
    seen_paths: set[Path] = set()
    for raw_row in rows:
        row = {str(key): str(value) for key, value in dict(raw_row).items()}
        report_id = row.get("id", "").strip()
        relative_path = row.get("path", "").strip()
        if not report_id or not relative_path:
            raise ValueError("each research manifest row requires id and path")
        source_path = (repo_root / relative_path).resolve()
        try:
            source_path.relative_to(repo_root)
        except ValueError as exc:
            raise ValueError(f"research path escapes repository: {relative_path}") from exc
        if report_id in seen_ids:
            raise ValueError(f"duplicate research id in manifest: {report_id}")
        if source_path in seen_paths:
            raise ValueError(f"duplicate research path in manifest: {relative_path}")
        if not source_path.is_file():
            raise FileNotFoundError(f"research report does not exist: {relative_path}")
        if row.get("admission") == VERIFIED_ADMISSION:
            validate_verified_manifest_row(row, repo_root=repo_root)
        seen_ids.add(report_id)
        seen_paths.add(source_path)
        candidates.append((row, source_path))
    return candidates


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
            topic.active_issue_ids = [
                row["issue_id"] for row in shadow[topic.id] if row["issue_id"] in issue_map
            ]
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
                "eventType": item.get("eventType") or "updated",
                "eventLabel": item.get("eventLabel") or "更新",
                "sourceStatus": item.get("sourceStatus") or "",
            }
            for item in items
        ),
        key=lambda item: item["updatedAt"] or "",
        reverse=True,
    )


def timeline_event(
    *,
    item: dict,
    timestamp: str,
    event_type: str,
    event_label: str,
    path: str | None = None,
) -> dict:
    return {
        "id": item["id"],
        "type": item["type"],
        "title": item["title"],
        "topicId": item.get("topicId"),
        "updatedAt": timestamp,
        "path": path or item["path"],
        "eventType": event_type,
        "eventLabel": event_label,
        "sourceStatus": str(item.get("status") or ""),
    }


def append_event(events: list[dict], event: dict) -> None:
    if not event.get("updatedAt"):
        return
    dedupe_key = (
        event["id"],
        event["type"],
        event["eventType"],
        event["updatedAt"],
    )
    if any(
        (
            item["id"],
            item["type"],
            item.get("eventType"),
            item.get("updatedAt"),
        )
        == dedupe_key
        for item in events
    ):
        return
    events.append(event)


def build_timeline(issues: list[dict], cards: list[dict], research: list[dict], articles: list[dict], news_rows: list[dict]) -> list[dict]:
    events: list[dict] = []

    for item in [*issues, *cards, *research]:
        created_at = first_nonempty(str(item.get("createdAt") or ""), str(item.get("mtime") or ""))
        updated_at = first_nonempty(str(item.get("updatedAt") or ""), str(item.get("mtime") or ""))
        append_event(
            events,
            timeline_event(
                item=item,
                timestamp=created_at,
                event_type="new",
                event_label="新增资产",
            ),
        )
        if updated_at and updated_at != created_at:
            append_event(
                events,
                timeline_event(
                    item=item,
                    timestamp=updated_at,
                    event_type="updated",
                    event_label="资产更新",
                ),
            )

    for item in articles:
        published_at = first_nonempty(str(item.get("publishedAt") or ""), str(item.get("updatedAt") or ""))
        updated_at = first_nonempty(str(item.get("updatedAt") or ""), published_at)
        append_event(
            events,
            timeline_event(
                item=item,
                timestamp=published_at,
                event_type="new",
                event_label="新文章入库",
            ),
        )
        if updated_at and updated_at != published_at:
            append_event(
                events,
                timeline_event(
                    item=item,
                    timestamp=updated_at,
                    event_type="updated",
                    event_label="文章状态更新" if item.get("status") != "digested" else "完成正式消化",
                ),
            )

    for item in news_rows:
        published_at = first_nonempty(str(item.get("publishedAt") or ""), str(item.get("updatedAt") or ""))
        updated_at = first_nonempty(str(item.get("updatedAt") or ""), published_at)
        news_path = "data/news_library/news_library.sqlite3"
        append_event(
            events,
            timeline_event(
                item=item,
                timestamp=published_at,
                event_type="new",
                event_label="新新闻入库",
                path=news_path,
            ),
        )
        if updated_at and updated_at != published_at:
            append_event(
                events,
                timeline_event(
                    item=item,
                    timestamp=updated_at,
                    event_type="updated",
                    event_label="状态更新" if item.get("status") != "digested" else "同步为已消化",
                    path=news_path,
                ),
            )

    return rebalance_timeline(sort_timeline(events), limit=360)


def rebalance_timeline(items: list[dict], *, limit: int) -> list[dict]:
    per_type_caps = {
        "news": 180,
        "article": 90,
        "issue": 30,
        "card": 30,
        "research": 30,
    }
    picked: list[dict] = []
    used_by_type = {key: 0 for key in per_type_caps}
    overflow: list[dict] = []

    for item in items:
        item_type = str(item.get("type") or "")
        cap = per_type_caps.get(item_type, limit)
        if used_by_type.get(item_type, 0) < cap:
            picked.append(item)
            used_by_type[item_type] = used_by_type.get(item_type, 0) + 1
        else:
            overflow.append(item)

    for item in overflow:
        if len(picked) >= limit:
            break
        picked.append(item)

    return picked[:limit]


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
    parser.add_argument("--news-window", type=int, default=500)
    args = parser.parse_args()

    repo_root = Path(args.repo_root).resolve()
    out_path = Path(args.out).resolve()
    index_root = repo_root / "data/semantic_pipeline_v2/index"
    article_root = repo_root / "data/semantic_pipeline_v2/articles"
    assets_root = SITE_ROOT / "assets"
    research_asset_stage = assets_root / ".research-staging"
    research_asset_final = assets_root / "research"
    if research_asset_stage.exists():
        shutil.rmtree(research_asset_stage)
    research_asset_stage.mkdir(parents=True, exist_ok=True)

    topics = parse_topic_registry(index_root / "topic_registry.md")
    shadow = parse_shadow(index_root / "registry_shadow_active_cards.md")

    issue_files = sorted(
        path
        for path in (index_root / "issue_cards").rglob("*.md")
        if ".bak." not in path.name
    )
    issues, issue_publication_audit = partition_public_items(
        "issues", [parse_issue_markdown(path) for path in issue_files]
    )

    merged_files = sorted((index_root / "merged_cards").glob("*.md"))
    cards, card_publication_audit = partition_public_items(
        "cards", [parse_merged_markdown(path) for path in merged_files]
    )

    research_source_items = [
        {
            "manifest": row,
            "path": row["path"],
            "source_path": str(source_path),
            "text": source_path.read_text(encoding="utf-8", errors="replace"),
        }
        for row, source_path in research_candidates(repo_root)
    ]
    public_research_sources, research_publication_audit = partition_public_items(
        "research", research_source_items
    )
    research = [
        parse_research_report(
            Path(source["source_path"]),
            report_id=source["manifest"]["id"],
            category=source["manifest"].get("category", "深度研究"),
            asset_stage_root=research_asset_stage,
            published_at=str(source["manifest"].get("published_at") or ""),
        )
        for source in public_research_sources
    ]
    article_dirs = sorted(path for path in article_root.iterdir() if path.is_dir())
    articles, article_publication_audit = partition_public_items(
        "articles", [parse_article_directory(path) for path in article_dirs]
    )
    news, news_total_count = parse_news_rows(
        repo_root=repo_root,
        article_ids={item["id"] for item in articles},
        limit=max(1, args.news_window),
    )
    research_objects = parse_research_objects(repo_root=repo_root)
    strategic_signals = parse_strategic_signals(repo_root=repo_root)

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
        + [item.get("updatedAt") or "" for item in news]
        + [item.get("updatedAt") or "" for item in research_objects]
        + [item.get("updatedAt") or "" for item in strategic_signals],
        default=datetime.now(tz=timezone.utc).isoformat(),
    )
    article_rows = articles
    news_rows = news
    relations = build_relations(topic_rows, issues, cards, research, article_rows, news_rows)
    timeline = build_timeline(issues, cards, research, article_rows, news_rows)

    source_fingerprint = {
        "generator": {
            "version": "ai-signals-build-v4",
            "build_site_data_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
            "research_manifest_sha256": hashlib.sha256(RESEARCH_MANIFEST.read_bytes()).hexdigest(),
        },
        "researchAssets": [
            (
                path.relative_to(research_asset_stage).as_posix(),
                hashlib.sha256(path.read_bytes()).hexdigest(),
            )
            for path in sorted(research_asset_stage.rglob("*"))
            if path.is_file()
        ],
        "topics": [(item["id"], item.get("lastUpdated")) for item in topic_rows],
        "issues": [(item["id"], item.get("updatedAt") or item.get("mtime")) for item in issues],
        "cards": [(item["id"], item.get("updatedAt") or item.get("mtime")) for item in cards],
        "research": [(item["id"], item.get("mtime")) for item in research],
        "articles": [(item["id"], item.get("updatedAt")) for item in article_rows],
        "news": [(item["id"], item.get("updatedAt"), item.get("status")) for item in news_rows],
        "objects": [(item["id"], item.get("updatedAt")) for item in research_objects],
        "signals": [(item["id"], item.get("updatedAt")) for item in strategic_signals],
        "newsTotalCount": news_total_count,
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
            "generatorVersion": "ai-signals-build-v4",
            "generator": "site-demo/scripts/build_site_data.py",
            "sourceRoots": {
                "index": "data/semantic_pipeline_v2/index",
                "research_manifest": "site-demo/scripts/research_publication_manifest.json",
                "research": ["research", "data/semantic_pipeline_v2/research_packs"],
                "articles": "data/semantic_pipeline_v2/articles",
                "news_db": "data/news_library/news_library.sqlite3",
                "research_object_db": "data/semantic_pipeline_v2/loop_engineering/news_value_research_cards.sqlite3",
                "strategic_signal_db": "data/semantic_pipeline_v2/loop_engineering/news_value_signal_registry.sqlite3",
            },
            "notes": [
                "Research reports are selected through an explicit publication manifest; process artifacts are excluded.",
                "News is a bounded recent-window projection of the local SQLite source.",
                "Reader-facing assets pass a public-information provenance gate before publication.",
            ],
            "publicationAudit": {
                "policyVersion": 1,
                "issues": issue_publication_audit,
                "cards": card_publication_audit,
                "research": research_publication_audit,
                "articles": article_publication_audit,
            },
        },
        "stats": {
            "topics": len(topic_rows),
            "issues": len(issues),
            "cards": len(cards),
            "research": len(research),
            "articles": len(article_rows),
            "news": news_total_count,
            "objects": len(research_objects),
            "signals": len(strategic_signals),
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
            "objects": research_objects,
            "signals": strategic_signals,
        },
        "newsMeta": {
            "strategy": "bounded_recent_window",
            "totalCount": news_total_count,
            "mirroredCount": len(news_rows),
            "windowLimit": max(1, args.news_window),
            "newestUpdatedAt": news_rows[0].get("updatedAt") if news_rows else "",
            "oldestPublishedAt": news_rows[-1].get("publishedAt") if news_rows else "",
            "scaleBoundary": "Full historical search requires a remote database/API; GitHub Pages only mirrors the recent window.",
        },
        "relations": relations,
        "timeline": timeline,
    }
    payload = sanitize_public_payload(payload, repo_root)
    validate_portal_payload(payload)

    if research_asset_final.exists():
        shutil.rmtree(research_asset_final)
    research_asset_stage.replace(research_asset_final)

    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


if __name__ == "__main__":
    main()
