import { searchRoute, searchSnippetText, searchTopMatches } from "./scripts/search-ranking.mjs";

const state = { data: null, timelineType: "all", timelineEvent: "all" };
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
  const response = await fetch("./data/site-data.json", { cache: "no-store" });
  if (!response.ok) throw new Error(`数据加载失败（${response.status}）`);
  state.data = normalizeData(await response.json());
  renderStats();
  renderTopicNav();
  bindSearch();
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
      : empty("没有找到匹配项。");
  });
}

function renderStats() {
  const { stats } = state.data;
  const rows = [
    ["专题", stats.topics], ["议题", stats.issues], ["知识卡", stats.cards],
    ["研究", stats.research], ["文章", stats.articles], ["新闻", stats.news],
  ];
  statsEl.innerHTML = rows.map(([label, value]) => `
    <a class="stat" href="#${({专题:"topics",议题:"issues",知识卡:"cards",研究:"research",文章:"articles",新闻:"news"})[label]}">
      <p class="eyebrow">${label}</p><strong>${Number(value || 0).toLocaleString("zh-CN")}</strong>
    </a>`).join("");
}

function renderTopicNav() {
  topicNavEl.innerHTML = state.data.topics.map((topic) => `
    <a class="topic-link" href="${routeHref("topic", topic.id)}">
      <strong>${escapeHtml(topic.title)}</strong>
      <div class="meta-strip"><span>${escapeHtml(topic.status)}</span><span>${topic.activeIssueIds.length} active</span></div>
    </a>`).join("");
}

function renderRoute() {
  searchResults.innerHTML = "";
  const [route, encodedId] = (window.location.hash.replace(/^#/, "") || "home").split("/");
  const id = decodeURIComponent(encodedId || "");
  if (route === "home") return renderHome();
  if (route === "timeline") return renderTimeline();
  if (id && Object.hasOwn(ROUTES, route)) return renderDetail(route, entity(route, id));
  if (Object.values(ROUTES).includes(route)) return renderAssetIndex(route, state.data[route]);
  renderMissing();
}

function renderHome() {
  const latest = state.data.timeline.slice(0, 10);
  const hotTopics = state.data.topics.slice().sort((a, b) => b.activeIssueIds.length - a.activeIssueIds.length).slice(0, 6);
  const meta = state.data.buildMeta || {};
  contentEl.innerHTML = `
    <section class="detail dashboard-hero">
      <div><p class="eyebrow">生产知识门户</p><h3>本地资产是唯一真相，网站自动发布只读快照</h3>
      <p>每次正式资产写入成功后自动重建、校验和发布；异常时不覆盖线上上一版。</p></div>
      <div class="build-state"><strong>最近同步 ${escapeHtml(formatTime(state.data.generatedAt))}</strong>
      <span>Build ${escapeHtml(meta.buildId || "-")} · 源版本 ${escapeHtml(meta.sourceRevision || "-")}</span></div>
    </section>
    <section class="entry-grid">
      ${entryCard("知识资产", "专题、议题、知识卡和研究成果", "topics")}
      ${entryCard("文章消化", "查看已入库文章及正式消化状态", "articles")}
      ${entryCard("新闻获取", "查看新闻库、来源与原文入口", "news")}
    </section>
    <div class="grid">
      <section class="list-panel"><p class="eyebrow">重点专题</p><h3>当前活跃议题最多</h3>${hotTopics.map(topicCard).join("")}</section>
      <section class="list-panel"><p class="eyebrow">最近更新</p><h3>跨资产时间线</h3>${latest.map(timelineRow).join("")}</section>
    </div>`;
}

function entryCard(title, copy, route) {
  return `<a class="entry-card" href="#${route}"><p class="eyebrow">入口</p><h3>${title}</h3><p>${copy}</p><span>进入 →</span></a>`;
}

function renderAssetIndex(kind, items) {
  const sorted = items.slice().sort((a, b) => timestamp(b) - timestamp(a));
  const newsMeta = state.data.newsMeta || {};
  const countLabel = kind === "news"
    ? `最近 ${Number(newsMeta.mirroredCount || items.length).toLocaleString("zh-CN")} / 总计 ${Number(newsMeta.totalCount || items.length).toLocaleString("zh-CN")}`
    : items.length.toLocaleString("zh-CN");
  contentEl.innerHTML = `<section class="list-panel"><p class="eyebrow">${typeLabel(kind.replace(/s$/, ""))}</p>
    <h3>${typeLabel(kind.replace(/s$/, ""))}（${countLabel}）</h3>
    ${kind === "news" ? `<p>为保证站点长期可用，这里只镜像最近窗口；SQLite 全量历史仍保留在本地，百万级历史检索将由远端数据库 API 提供。</p>` : ""}
    ${sorted.length ? sorted.slice(0, 500).map((item) => assetRow(item)).join("") : empty("暂无数据。")}
    ${sorted.length > 500 ? `<div class="empty">为保证浏览性能，本页先展示最近 500 条；其余内容可通过全站搜索定位。</div>` : ""}
  </section>`;
}

function renderDetail(type, item) {
  if (!item) return renderMissing();
  const relations = relatedAssets(type, item.id);
  const canonical = `${location.origin}${location.pathname}${routeHref(type, item.id)}`;
  const body = item.html || (item.summary ? `<p>${escapeHtml(item.summary)}</p>` : "");
  contentEl.innerHTML = `
    <section class="detail">
      <div class="detail-title"><div><p class="eyebrow">${typeLabel(type)}详情</p><h3>${escapeHtml(item.title)}</h3></div>
      <button class="copy-link" data-copy="${escapeHtml(canonical)}">复制稳定链接</button></div>
      <div class="meta-strip">
        <span>${escapeHtml(item.id)}</span>${item.status ? `<span>${escapeHtml(item.status)}</span>` : ""}
        ${item.sourceId ? `<span>${escapeHtml(item.sourceId)}</span>` : ""}
        ${item.sourceArticleCount != null ? `<span>${item.sourceArticleCount} 篇证据文章</span>` : ""}
        <span>更新 ${escapeHtml(formatTime(item.updatedAt || item.mtime || item.publishedAt || item.lastUpdated))}</span>
      </div>
      ${item.canonicalQuestion ? `<div class="question"><strong>核心问题</strong><p>${escapeHtml(item.canonicalQuestion)}</p></div>` : ""}
      ${item.summary ? `<div class="summary"><strong>摘要</strong><p>${escapeHtml(item.summary)}</p></div>` : ""}
      <div class="pill-row">
        ${item.url ? `<a class="pill" href="${escapeHtml(item.url)}" target="_blank" rel="noreferrer">查看原文 ↗</a>` : ""}
        ${item.articleId ? `<a class="pill" href="${routeHref("article", item.articleId)}">查看已消化文章</a>` : ""}
      </div>
    </section>
    ${renderRelations(relations)}
    ${body ? `<section class="detail"><p class="eyebrow">完整内容</p><article>${body}</article></section>` : ""}`;
  const button = contentEl.querySelector("[data-copy]");
  button?.addEventListener("click", async () => {
    await navigator.clipboard.writeText(button.dataset.copy);
    button.textContent = "已复制";
  });
}

function renderRelations(items) {
  return `<section class="list-panel relation-panel"><p class="eyebrow">关系导航</p><h3>相关资产（${items.length}）</h3>
    ${items.length ? `<div class="relation-grid">${items.map(({ item, relation }) => `
      <a class="relation-node" href="${routeHref(item.type, item.id)}"><span>${typeLabel(item.type)}</span>
      <strong>${escapeHtml(item.title)}</strong><small>${escapeHtml(relationLabel(relation.type))}</small></a>`).join("")}</div>` : empty("当前尚无可验证的关联资产。")}
  </section>`;
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
  const types = ["all", "issue", "card", "research", "article", "news"];
  const eventTypes = ["all", "new", "updated"];
  const filtered = state.data.timeline.filter((item) => {
    const typePass = state.timelineType === "all" || item.type === state.timelineType;
    const eventPass = state.timelineEvent === "all" || item.eventType === state.timelineEvent;
    return typePass && eventPass;
  });
  contentEl.innerHTML = `<section class="list-panel"><p class="eyebrow">时间线</p><h3>按更新时间追踪资产变化</h3>
    <div class="filter-stack">
      <div class="filter-row">${types.map((type) => `<button class="filter ${state.timelineType === type ? "active" : ""}" data-type="${type}">${type === "all" ? "全部类型" : typeLabel(type)}</button>`).join("")}</div>
      <div class="filter-row">${eventTypes.map((eventType) => `<button class="filter ${state.timelineEvent === eventType ? "active" : ""}" data-event-type="${eventType}">${timelineEventFilterLabel(eventType)}</button>`).join("")}</div>
    </div>
    ${filtered.slice(0, 300).map(timelineRow).join("") || empty("该类型暂无更新。")}</section>`;
  contentEl.querySelectorAll("[data-type]").forEach((button) => button.addEventListener("click", () => {
    state.timelineType = button.dataset.type; renderTimeline();
  }));
  contentEl.querySelectorAll("[data-event-type]").forEach((button) => button.addEventListener("click", () => {
    state.timelineEvent = button.dataset.eventType; renderTimeline();
  }));
}

function entity(type, id) {
  const rows = type === "topic" ? state.data.topics : state.data[ROUTES[type] || `${type}s`] || [];
  return rows.find((item) => item.id === id);
}

function topicCard(topic) {
  return `<a class="list-link" href="${routeHref("topic", topic.id)}"><strong>${escapeHtml(topic.title)}</strong>
    <span>${topic.activeIssueIds.length} 个活跃议题 · ${escapeHtml(topic.status)}</span></a>`;
}

function assetRow(item) {
  return `<a class="list-link" href="${routeHref(item.type || "topic", item.id)}"><strong>${escapeHtml(item.title)}</strong>
    <span>${escapeHtml(typeLabel(item.type))} · ${escapeHtml(item.status || "")} · ${escapeHtml(formatTime(item.updatedAt || item.mtime || item.publishedAt || item.lastUpdated))}</span></a>`;
}

function timelineRow(item) {
  return `<a class="list-link timeline-row" href="${routeHref(item.type, item.id)}">
    <div class="timeline-kind">
      <span class="type-badge">${typeLabel(item.type)}</span>
      <span class="event-badge ${escapeHtml(item.eventType || "updated")}">${escapeHtml(item.eventLabel || timelineEventFilterLabel(item.eventType || "updated"))}</span>
    </div>
    <div class="timeline-copy">
      <strong>${escapeHtml(item.title)}</strong>
      <span>${escapeHtml(timelineStatusText(item))}</span>
    </div>
    <time>${escapeHtml(formatTime(item.updatedAt))}</time>
  </a>`;
}

function timelineEventFilterLabel(value) {
  return ({ all: "全部事件", new: "新增", updated: "更新" })[value] || value;
}

function timelineStatusText(item) {
  const segments = [];
  if (item.sourceStatus) segments.push(statusLabel(item.sourceStatus));
  if (item.topicId) segments.push(`专题 ${item.topicId}`);
  if (!segments.length) segments.push(item.eventType === "new" ? "新增进入统一时间线" : "统一记录最近一次变更");
  return segments.join(" · ");
}

function statusLabel(status) {
  return ({
    active: "进行中",
    provisional: "暂存",
    published: "已发布",
    digested: "已消化",
    digest_ready: "Digest 已完成",
    new: "新入库",
  })[status] || status;
}

function relationLabel(value) {
  const labels = { topic_issue_declared: "专题声明议题", topic_issue_active: "活跃议题", topic_card_related: "专题关联知识卡", topic_research_related: "专题关联研究", issue_topic_parent: "所属专题", card_topic_parent: "所属专题", research_topic_parent: "所属专题", news_article_materialized: "已形成文章", issue_article_evidence: "议题证据", card_article_evidence: "知识卡证据", research_article_evidence: "研究证据" };
  return labels[value] || value.replaceAll("_", " ");
}

function typeLabel(type) {
  return ({ topic:"专题", topics:"专题", issue:"议题", issues:"议题", card:"知识卡", cards:"知识卡", research:"研究", article:"文章", articles:"文章", news:"新闻" })[type] || type || "资产";
}

function renderMissing() { contentEl.innerHTML = empty("没有找到对应资产，请从侧边栏或搜索框继续查找。"); }
function empty(text) { return `<div class="empty">${escapeHtml(text)}</div>`; }
function timestamp(item) { const value = Date.parse(item.updatedAt || item.mtime || item.publishedAt || item.lastUpdated || ""); return Number.isFinite(value) ? value : 0; }
function formatTime(value) { if (!value) return "-"; const date = new Date(value); return Number.isNaN(date.getTime()) ? String(value) : date.toLocaleString("zh-CN", { hour12: false }); }
function snippet(text, query) { const value = String(text || ""); const idx = value.toLowerCase().indexOf(query.toLowerCase()); const start = Math.max(0, idx < 0 ? 0 : idx - 28); return value.slice(start, start + 110); }
function escapeHtml(value) { return String(value ?? "").replaceAll("&", "&amp;").replaceAll("<", "&lt;").replaceAll(">", "&gt;").replaceAll('"', "&quot;").replaceAll("'", "&#039;"); }

init().catch((error) => { contentEl.innerHTML = `<div class="empty">站点初始化失败：${escapeHtml(error.message)}</div>`; });
