import { searchRoute, searchTopMatches } from "./scripts/search-ranking.mjs";

const state = { data: null, timelineType: "all", timelineEvent: "all", mermaid: null };
const contentEl = document.getElementById("content");
const statsEl = document.getElementById("stats");
const topicNavEl = document.getElementById("topic-nav");
const searchInput = document.getElementById("search-input");
const searchResults = document.getElementById("search-results");

const ROUTES = {
  topic: "topics",
  issue: "issues",
  card: "cards",
  research: "research",
  article: "articles",
  news: "news",
};

async function init() {
  searchInput.disabled = true;
  const response = await fetch("./data/site-data.json", { cache: "no-store" });
  if (!response.ok) throw new Error(`数据加载失败（${response.status}）`);
  state.data = normalizeData(await response.json());
  renderStats();
  renderTopicNav();
  bindSearch();
  searchInput.disabled = false;
  window.addEventListener("hashchange", renderRoute);
  renderRoute();
}

function normalizeData(raw) {
  const collections = raw.collections || {};
  return {
    ...raw,
    topics: collections.topics || raw.topics || [],
    issues: collections.issues || raw.issues || [],
    cards: collections.cards || raw.cards || [],
    research: collections.research || raw.research || [],
    articles: collections.articles || raw.articles || [],
    news: collections.news || raw.news || [],
    relations: raw.relations || [],
    timeline: raw.timeline || [],
  };
}

function routeHref(type, id = "") {
  return id ? `#${type}/${encodeURIComponent(id)}` : `#${ROUTES[type] || type}`;
}

function bindSearch() {
  searchInput.addEventListener("input", () => {
    const query = searchInput.value.trim();
    if (!query) return (searchResults.innerHTML = "");
    const matches = searchTopMatches(state.data, query, 10);
    searchResults.innerHTML = matches.length
      ? matches.map(({ item, snippetText }) => `
          <a class="search-hit" href="${routeHref(searchRoute(item), item.id)}">
            <strong>${escapeHtml(item.title)}</strong>
            <span>${escapeHtml(typeLabel(item.type))} · ${escapeHtml(snippet(snippetText, query))}</span>
          </a>`).join("")
      : empty("没有找到匹配内容。");
  });
}

function renderStats() {
  const { stats } = state.data;
  const rows = [
    ["新闻资讯", stats.news, "news"],
    ["深度研究", stats.research, "research"],
    ["专题观察", stats.topics, "topics"],
    ["分析卡片", stats.issues, "issues"],
    ["综合研判", stats.cards, "cards"],
    ["文章解读", stats.articles, "articles"],
  ];
  statsEl.innerHTML = rows.map(([label, value, route]) => `
    <a class="stat" href="#${route}">
      <p>${label}</p><strong>${Number(value || 0).toLocaleString("zh-CN")}</strong>
    </a>`).join("");
}

function renderTopicNav() {
  topicNavEl.innerHTML = state.data.topics.map((topic) => `
    <a class="topic-link" href="${routeHref("topic", topic.id)}">
      <strong>${escapeHtml(topic.title)}</strong>
      <div class="meta-strip"><span>${escapeHtml(statusLabel(topic.status))}</span><span>${topic.activeIssueIds.length} 个议题</span></div>
    </a>`).join("");
}

function renderRoute() {
  searchResults.innerHTML = "";
  const [route, encodedId] = (window.location.hash.replace(/^#/, "") || "home").split("/");
  const id = decodeURIComponent(encodedId || "");
  setActiveNav(route);
  if (route === "home") return renderHome();
  if (route === "timeline") return renderTimeline();
  if (id && Object.hasOwn(ROUTES, route)) return renderDetail(route, entity(route, id));
  if (Object.values(ROUTES).includes(route)) return renderAssetIndex(route, state.data[route]);
  renderMissing();
}

function setActiveNav(route) {
  const listRoute = ROUTES[route] || route;
  document.querySelectorAll(".nav a").forEach((link) => {
    link.classList.toggle("active", link.getAttribute("href") === `#${listRoute}`);
  });
}

function renderHome() {
  const latestNews = state.data.news.slice().sort((a, b) => timestamp(b) - timestamp(a)).slice(0, 9);
  const latestResearch = state.data.research.slice().sort((a, b) => timestamp(b) - timestamp(a)).slice(0, 6);
  const [lead, ...briefs] = latestNews;
  contentEl.innerHTML = `
    <section class="news-front">
      <div class="section-heading"><div><p class="eyebrow">今日关注</p><h3>最新 AI 资讯</h3></div><a href="#news">查看全部新闻 →</a></div>
      <div class="lead-grid">
        ${lead ? `<a class="lead-story" href="${routeHref("news", lead.id)}"><span class="news-label">头条</span><h3>${escapeHtml(lead.title)}</h3><p>${escapeHtml(displaySummary(lead.summary || "来自公开信息源的最新动态。"))}</p><time>${escapeHtml(formatTime(lead.publishedAt || lead.updatedAt))}</time></a>` : empty("暂无新闻。")}
        <div class="brief-list">${briefs.map(newsBrief).join("")}</div>
      </div>
    </section>
    <section class="research-front">
      <div class="section-heading"><div><p class="eyebrow">趋势与洞察</p><h3>深度研究</h3></div><a href="#research">查看全部 ${state.data.research.length} 份研究 →</a></div>
      <div class="research-grid">${latestResearch.map(researchCard).join("")}</div>
    </section>`;
}

function newsBrief(item, index) {
  return `<a class="news-brief" href="${routeHref("news", item.id)}"><span>${String(index + 2).padStart(2, "0")}</span><div><strong>${escapeHtml(item.title)}</strong><small>${escapeHtml(sourceLabel(item.sourceId))} · ${escapeHtml(formatDate(item.publishedAt || item.updatedAt))}</small></div></a>`;
}

function researchCard(item) {
  return `<a class="research-card" href="${routeHref("research", item.id)}"><span>${escapeHtml(item.category || "深度研究")}</span><h4>${escapeHtml(item.title)}</h4><p>${escapeHtml(displaySummary(item.summary || ""))}</p><small>${Number(item.diagramCount || 0) ? `${Number(item.diagramCount)} 张图表 · ` : ""}${escapeHtml(formatDate(item.updatedAt || item.mtime))}</small></a>`;
}

function renderAssetIndex(kind, items) {
  const sorted = items.slice().sort((a, b) => timestamp(b) - timestamp(a));
  const newsMeta = state.data.newsMeta || {};
  const countLabel = kind === "news"
    ? `最近 ${Number(newsMeta.mirroredCount || items.length).toLocaleString("zh-CN")} 条 / 累计 ${Number(newsMeta.totalCount || items.length).toLocaleString("zh-CN")} 条`
    : `${items.length.toLocaleString("zh-CN")} 项`;
  const intro = kind === "news"
    ? "按发布时间展示最近资讯，原始信息均来自公开来源。"
    : kind === "research"
      ? "这里仅收录正式研究成品，不包含提示词、草稿、素材账本和审阅过程。"
      : "按最近更新时间排列。";
  const rows = kind === "research"
    ? `<div class="research-grid research-index">${sorted.map(researchCard).join("")}</div>`
    : `<div class="editorial-list">${sorted.slice(0, 500).map((item) => assetRow(item)).join("")}</div>`;
  contentEl.innerHTML = `<section class="list-panel index-page"><div class="section-heading"><div><p class="eyebrow">${typeLabel(kind)}</p><h3>${typeLabel(kind)} <small>${countLabel}</small></h3></div></div><p class="index-intro">${intro}</p>${rows || empty("暂无内容。")}</section>`;
}

function renderDetail(type, item) {
  if (!item) return renderMissing();
  const relations = relatedAssets(type, item.id);
  const canonical = `${location.origin}${location.pathname}${routeHref(type, item.id)}`;
  const body = item.html || (item.summary ? `<p>${escapeHtml(item.summary)}</p>` : "");
  contentEl.innerHTML = `
    <section class="detail detail-header">
      <div class="detail-title"><div><p class="eyebrow">${typeLabel(type)}</p><h3>${escapeHtml(item.title)}</h3></div><button class="copy-link" data-copy="${escapeHtml(canonical)}">复制链接</button></div>
      <div class="meta-strip">
        ${item.category ? `<span>${escapeHtml(item.category)}</span>` : ""}
        ${item.status ? `<span>${escapeHtml(statusLabel(item.status))}</span>` : ""}
        ${item.sourceId ? `<span>${escapeHtml(sourceLabel(item.sourceId))}</span>` : ""}
        ${item.sourceArticleCount != null ? `<span>${item.sourceArticleCount} 篇参考文章</span>` : ""}
        ${item.diagramCount ? `<span>${item.diagramCount} 张图表</span>` : ""}
        <span>更新于 ${escapeHtml(formatTime(item.updatedAt || item.mtime || item.publishedAt || item.lastUpdated))}</span>
      </div>
      ${item.canonicalQuestion ? `<div class="question"><strong>核心问题</strong><p>${escapeHtml(item.canonicalQuestion)}</p></div>` : ""}
      ${item.summary && type !== "research" ? `<div class="summary"><strong>内容摘要</strong><p>${escapeHtml(item.summary)}</p></div>` : ""}
      <div class="pill-row">
        ${item.url ? `<a class="pill" href="${escapeHtml(item.url)}" target="_blank" rel="noreferrer">查看公开原文 ↗</a>` : ""}
        ${item.articleId ? `<a class="pill" href="${routeHref("article", item.articleId)}">查看文章解读</a>` : ""}
      </div>
    </section>
    ${relations.length ? renderRelations(relations) : ""}
    ${body ? `<section class="detail report-body"><p class="eyebrow">${type === "research" ? "研究正文" : "完整内容"}</p><article>${body}</article></section>` : ""}`;
  const button = contentEl.querySelector("[data-copy]");
  button?.addEventListener("click", async () => {
    await navigator.clipboard.writeText(button.dataset.copy);
    button.textContent = "已复制";
  });
  if (type === "issue" || type === "card") {
    decorateAnalysisCard(contentEl.querySelector(".report-body article"));
  }
  void renderMermaidDiagrams(contentEl);
}

function decorateAnalysisCard(article) {
  if (!article) return;
  article.classList.add("analysis-card-body");
  const englishHeadings = {
    "基本信息": "Metadata",
    "核心问题": "Canonical Question",
    "为什么重要": "Why It Matters",
    "当前观点": "Current Viewpoints",
    "关键证据": "Key Evidence",
    "作用机制": "Mechanisms",
    "风险与不确定性": "Risks / Uncertainties",
    "相关文章": "Related Articles",
    "已归档或替换": "Archived / Replaced",
    "退役记录": "Retire Record",
  };
  const sectionClasses = {
    "基本信息": "analysis-meta",
    "核心问题": "analysis-question",
    "为什么重要": "analysis-importance",
    "当前观点": "analysis-viewpoints",
    "关键证据": "analysis-evidence",
    "作用机制": "analysis-mechanisms",
    "风险与不确定性": "analysis-risks",
    "相关文章": "analysis-related",
    "已归档或替换": "analysis-archive",
    "退役记录": "analysis-archive",
  };
  const fragment = document.createDocumentFragment();
  let section = null;
  for (const node of [...article.children]) {
    if (node.tagName === "H2") {
      const label = node.textContent.trim();
      section = document.createElement("section");
      section.className = `analysis-section ${sectionClasses[label] || "analysis-general"}`;
      if (englishHeadings[label]) node.title = englishHeadings[label];
      fragment.append(section);
    }
    (section || fragment).append(node);
  }
  article.replaceChildren(fragment);
}

async function renderMermaidDiagrams(root) {
  const codeBlocks = [...root.querySelectorAll("pre > code.language-mermaid")];
  if (!codeBlocks.length) return;
  const nodes = codeBlocks.map((code) => {
    const wrapper = document.createElement("div");
    wrapper.className = "mermaid-chart";
    wrapper.textContent = code.textContent;
    code.parentElement.replaceWith(wrapper);
    return wrapper;
  });
  try {
    if (!state.mermaid) {
      const module = await import("https://cdn.jsdelivr.net/npm/mermaid@11/dist/mermaid.esm.min.mjs");
      state.mermaid = module.default;
      state.mermaid.initialize({ startOnLoad: false, securityLevel: "strict", theme: "neutral", fontFamily: "Noto Sans SC, PingFang SC, sans-serif" });
    }
    await state.mermaid.run({ nodes });
  } catch (error) {
    nodes.forEach((node) => {
      if (!node.querySelector("svg")) {
        node.classList.add("diagram-fallback");
        node.insertAdjacentHTML("afterbegin", `<strong>图表暂时无法渲染</strong><small>${escapeHtml(error.message || "未知错误")}</small>`);
      }
    });
  }
}

function renderRelations(items) {
  return `<section class="list-panel relation-panel"><div class="section-heading"><div><p class="eyebrow">延伸阅读</p><h3>相关内容</h3></div></div><div class="relation-grid">${items.slice(0, 18).map(({ item, relation }) => `<a class="relation-node" href="${routeHref(item.type, item.id)}"><span>${typeLabel(item.type)}</span><strong>${escapeHtml(item.title)}</strong><small>${escapeHtml(relationLabel(relation.type))}</small></a>`).join("")}</div></section>`;
}

function relatedAssets(type, id) {
  const found = [];
  const seen = new Set();
  for (const relation of state.data.relations) {
    let targetType = "", targetId = "";
    if (relation.fromType === type && relation.fromId === id) [targetType, targetId] = [relation.toType, relation.toId];
    else if (relation.toType === type && relation.toId === id) [targetType, targetId] = [relation.fromType, relation.fromId];
    if (!targetId || seen.has(`${targetType}:${targetId}`)) continue;
    const item = entity(targetType, targetId);
    if (item) { seen.add(`${targetType}:${targetId}`); found.push({ item: { ...item, type: targetType }, relation }); }
  }
  return found.sort((a, b) => typeLabel(a.item.type).localeCompare(typeLabel(b.item.type), "zh-CN"));
}

function renderTimeline() {
  const types = ["all", "news", "research", "article", "issue", "card"];
  const eventTypes = ["all", "new", "updated"];
  const filtered = state.data.timeline.filter((item) => (state.timelineType === "all" || item.type === state.timelineType) && (state.timelineEvent === "all" || item.eventType === state.timelineEvent));
  contentEl.innerHTML = `<section class="list-panel index-page"><div class="section-heading"><div><p class="eyebrow">更新记录</p><h3>近期内容变化</h3></div></div><div class="filter-stack"><div class="filter-row">${types.map((type) => `<button class="filter ${state.timelineType === type ? "active" : ""}" data-type="${type}">${type === "all" ? "全部类型" : typeLabel(type)}</button>`).join("")}</div><div class="filter-row">${eventTypes.map((eventType) => `<button class="filter ${state.timelineEvent === eventType ? "active" : ""}" data-event-type="${eventType}">${timelineEventFilterLabel(eventType)}</button>`).join("")}</div></div><div class="editorial-list">${filtered.slice(0, 300).map(timelineRow).join("") || empty("该类型暂无更新。")}</div></section>`;
  contentEl.querySelectorAll("[data-type]").forEach((button) => button.addEventListener("click", () => { state.timelineType = button.dataset.type; renderTimeline(); }));
  contentEl.querySelectorAll("[data-event-type]").forEach((button) => button.addEventListener("click", () => { state.timelineEvent = button.dataset.eventType; renderTimeline(); }));
}

function entity(type, id) {
  const rows = type === "topic" ? state.data.topics : state.data[ROUTES[type] || `${type}s`] || [];
  return rows.find((item) => item.id === id);
}

function assetRow(item) {
  return `<a class="list-link" href="${routeHref(item.type || "topic", item.id)}"><div><span class="type-badge">${escapeHtml(typeLabel(item.type))}</span><strong>${escapeHtml(item.title)}</strong></div><span>${escapeHtml(sourceLabel(item.sourceId || statusLabel(item.status || "")))} · ${escapeHtml(formatTime(item.updatedAt || item.mtime || item.publishedAt || item.lastUpdated))}</span></a>`;
}

function timelineRow(item) {
  return `<a class="list-link timeline-row" href="${routeHref(item.type, item.id)}"><div class="timeline-kind"><span class="type-badge">${typeLabel(item.type)}</span><span class="event-badge ${escapeHtml(item.eventType || "updated")}">${escapeHtml(item.eventLabel || timelineEventFilterLabel(item.eventType || "updated"))}</span></div><div class="timeline-copy"><strong>${escapeHtml(item.title)}</strong><span>${escapeHtml(timelineStatusText(item))}</span></div><time>${escapeHtml(formatTime(item.updatedAt))}</time></a>`;
}

function timelineEventFilterLabel(value) { return ({ all: "全部事件", new: "新增", updated: "更新" })[value] || value; }
function timelineStatusText(item) { return item.sourceStatus ? statusLabel(item.sourceStatus) : (item.eventType === "new" ? "新增内容" : "内容更新"); }
function sourceLabel(value) { return String(value || "公开信息").replace(/^www\./, ""); }
function statusLabel(status) { return ({ active: "持续关注", provisional: "观察中", published: "已发布", digested: "已解读", digest_ready: "已完成解读", new: "最新入库", raw: "待解读" })[status] || status || ""; }
function relationLabel(value) { return ({ topic_issue_declared: "所属专题", topic_issue_active: "持续跟踪", topic_card_related: "相关分析", topic_research_related: "相关研究", issue_topic_parent: "所属专题", card_topic_parent: "所属专题", research_topic_parent: "所属专题", news_article_materialized: "已形成解读", issue_article_evidence: "参考文章", card_article_evidence: "参考文章", research_article_evidence: "参考文章" })[value] || "相关内容"; }
function typeLabel(type) { return ({ topic: "专题观察", topics: "专题观察", issue: "分析卡片", issues: "分析卡片", card: "综合研判", cards: "综合研判", research: "深度研究", article: "文章解读", articles: "文章解读", news: "新闻资讯" })[type] || type || "内容"; }
function renderMissing() { contentEl.innerHTML = empty("没有找到对应内容，请从左侧栏目或搜索框继续查找。"); }
function empty(text) { return `<div class="empty">${escapeHtml(text)}</div>`; }
function timestamp(item) { const value = Date.parse(item.publishedAt || item.updatedAt || item.mtime || item.lastUpdated || ""); return Number.isFinite(value) ? value : 0; }
function formatTime(value) { if (!value) return "-"; const date = new Date(value); return Number.isNaN(date.getTime()) ? String(value) : date.toLocaleString("zh-CN", { hour12: false }); }
function formatDate(value) { if (!value) return "-"; const date = new Date(value); return Number.isNaN(date.getTime()) ? String(value) : date.toLocaleDateString("zh-CN", { year: "numeric", month: "2-digit", day: "2-digit" }); }
function displaySummary(value) { return String(value || "").replace(/[*_~`#>-]+/g, " ").replace(/\s+/g, " ").trim(); }
function snippet(text, query) { const value = String(text || ""); const idx = value.toLowerCase().indexOf(query.toLowerCase()); const start = Math.max(0, idx < 0 ? 0 : idx - 28); return value.slice(start, start + 110); }
function escapeHtml(value) { return String(value ?? "").replaceAll("&", "&amp;").replaceAll("<", "&lt;").replaceAll(">", "&gt;").replaceAll('"', "&quot;").replaceAll("'", "&#039;"); }

init().catch((error) => { contentEl.innerHTML = `<div class="empty">页面加载失败：${escapeHtml(error.message)}</div>`; });
