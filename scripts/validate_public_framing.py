#!/usr/bin/env python3
"""Reject legacy public branding in user-visible pages and public docs."""

from __future__ import annotations

import json
from pathlib import Path


SITE_ROOT = Path(__file__).resolve().parents[1]
FILES = [
    SITE_ROOT / "index.html",
    SITE_ROOT / "README.md",
    SITE_ROOT / "PRODUCTION_RUNBOOK.md",
    SITE_ROOT / "NEWS_SYNC_ARCHITECTURE.md",
    SITE_ROOT / "TASK_COVERAGE.md",
]
BANNED = [
    "Knowledge Atlas",
    "Knowledge Asset Portal",
    "Knowledge Portal",
    "知识资产门户",
    "生产知识门户",
    "公开可访问的知识资产",
    "kfc-knowledge-atlas-demo-20260715",
]


def main() -> int:
    violations: list[str] = []
    for path in FILES:
        text = path.read_text(encoding="utf-8")
        for phrase in BANNED:
            if phrase.lower() in text.lower():
                violations.append(f"{path.name}: {phrase}")
    if violations:
        raise SystemExit("legacy public framing found: " + "; ".join(violations))
    index = (SITE_ROOT / "index.html").read_text(encoding="utf-8")
    assert "<title>AI 资讯观察</title>" in index
    ordered = ["新闻资讯", "深度研究", "专题观察", "分析卡片", "综合研判", "文章解读", "更新记录", "首页"]
    positions = [index.index(label) for label in ordered]
    assert positions == sorted(positions), positions
    print(json.dumps({"status": "passed", "checked_files": len(FILES), "legacy_phrases": 0, "first_navigation": "新闻资讯"}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
