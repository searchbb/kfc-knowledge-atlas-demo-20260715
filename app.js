const state = {
  data: null,
};

const contentEl = document.getElementById("content");
const statsEl = document.getElementById("stats");
const topicNavEl = document.getElementById("topic-nav");
const searchInput = document.getElementById("search-input");
const searchResults = document.getElementById("search-results");

async function init() {
  const response = await fetch("./data/site-data.json");
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

function bindSearch() {
  searchInput.addEventListener("input", () => {
    const query = searchInput.value.trim().toLowerCase();
    if (!query) {
      searchResults.innerHTML = "";
      return;
    }
    const pool = [
      ...state.data.topics.map((item) => ({ ...item, type: "topic" })),
      ...state.data.issues,
      ...state.data.cards,
      ...state.data.research,
      ...state.data.articles,
    ];
    const matches = pool
      .map((item) => ({ item, score: searchScore(item, query) }))
      .filter(({ score }) => score > 0)
      .sort((left, right) => right.score - left.score)
      .map(({ item }) => item)
      .slice(0, 8);

    searchResults.innerHTML = matches.length
      ? matches
          .map(
            (item) => `
              <a class="search-hit" href="#${searchRoute(item)}/${item.id}">
                <strong>${escapeHtml(item.title)}</strong>
                <span>${item.type.toUpperCase()} · ${escapeHtml(item.id)} · ${escapeHtml(snippet(searchSnippetText(item), query))}</span>
              </a>
            `,
          )
          .join("")
      : `<div class="empty">没有找到匹配项。</div>`;
  });
}

function renderStats() {
  const { stats } = state.data;
  const rows = [
    ["Topics", stats.topics],
    ["Issues", stats.issues],
    ["Cards", stats.cards],
    ["Research", stats.research],
    ["Active", stats.activeIssues],
    ["Provisional", stats.provisionalIssues],
  ];
  statsEl.innerHTML = rows
    .map(
      ([label, value]) => `
        <div class="stat">
          <p class="eyebrow">${label}</p>
          <strong>${value}</strong>
        </div>
      `,
    )
    .join("");
}

function renderTopicNav() {
  topicNavEl.innerHTML = state.data.topics
    .map(
      (topic) => `
        <a class="topic-link" href="#topic/${topic.id}">
          <strong>${escapeHtml(topic.title)}</strong>
          <div class="meta-strip">
            <span>${escapeHtml(topic.status)}</span>
            <span>${topic.activeIssueIds.length} active</span>
          </div>
        </a>
      `,
    )
    .join("");
}

function renderRoute() {
  const [route, id] = (window.location.hash.replace(/^#/, "") || "home").split("/");
  switch (route) {
    case "topics":
      renderTopicIndex();
      break;
    case "topic":
      renderTopicDetail(id);
      break;
    case "articles":
      renderAssetIndex("articles", state.data.articles, "Article 详情");
      break;
    case "issues":
      renderAssetIndex("issues", state.data.issues, "Issue 详情");
      break;
    case "article":
      renderArticleDetail(state.data.articles.find((item) => item.id === id));
      break;
    case "issue":
      renderAssetDetail(state.data.issues.find((item) => item.id === id), "Issue");
      break;
    case "cards":
      renderAssetIndex("cards", state.data.cards, "Merged Card 详情");
      break;
    case "card":
      renderAssetDetail(state.data.cards.find((item) => item.id === id), "Card");
      break;
    case "research":
      renderAssetIndex("research", state.data.research, "Research 详情");
      break;
    case "researchItem":
    case "researchitem":
      renderAssetDetail(state.data.research.find((item) => item.id === id), "Research");
      break;
    case "research-detail":
      renderAssetDetail(state.data.research.find((item) => item.id === id), "Research");
      break;
    case "researchpack":
      renderAssetDetail(state.data.research.find((item) => item.id === id), "Research");
      break;
    case "researchdoc":
      renderAssetDetail(state.data.research.find((item) => item.id === id), "Research");
      break;
    case "researches":
      renderAssetIndex("research", state.data.research, "Research 详情");
      break;
    case "timeline":
      renderTimeline();
      break;
    case "home":
    default:
      renderHome();
  }
}

function renderHome() {
  const latest = state.data.timeline.slice(0, 8);
  const hotTopics = state.data.topics
    .slice()
    .sort((a, b) => b.activeIssueIds.length - a.activeIssueIds.length)
    .slice(0, 6);

  contentEl.innerHTML = `
    <div class="grid">
      <section class="card">
        <p class="eyebrow">Dashboard</p>
        <h3>首页读什么</h3>
        <p>先看 Topic 热区与最近更新时间，再进入具体 Issue / Card / Research 详情。这个 demo 直接把 markdown 细节内容渲染进站点，而不是只停留在 summary 列表。</p>
        <div class="pill-row">
          <span class="pill">最新更新 ${escapeHtml(formatTime(state.data.stats.latestUpdate))}</span>
          <span class="pill">全站搜索已开启</span>
          <span class="pill">侧边栏固定 Topic 导航</span>
        </div>
      </section>
      <section class="card">
        <p class="eyebrow">Deployment Notes</p>
        <h3>演示边界</h3>
        <p>当前版本聚焦 KFC 正式索引里的 Topic / Issue Card / Merged Card / 关键 Research 报告。它用真实目录生成，不是手写假数据；如果 Martin 点进某个条目，会看到完整 markdown 内容而不是缩略摘要。</p>
        <div class="pill-row">
          <span class="pill accent">适合今晚验证 UI/结构/细节粒度</span>
        </div>
      </section>
    </div>
    <section class="list-panel">
      <p class="eyebrow">Top Topics</p>
      <h3>最值得先点开的 Topics</h3>
      ${hotTopics.map(topicCard).join("")}
    </section>
    <section class="list-panel">
      <p class="eyebrow">Recent Changes</p>
      <h3>最近更新时间线</h3>
      ${latest.map(timelineRow).join("")}
    </section>
  `;
}

function renderTopicIndex() {
  contentEl.innerHTML = `
    <section class="list-panel">
      <p class="eyebrow">Topics</p>
      <h3>全部 Topic</h3>
      ${state.data.topics.map(topicCard).join("")}
    </section>
  `;
}

function renderTopicDetail(topicId) {
  const topic = state.data.topics.find((item) => item.id === topicId);
  if (!topic) return renderMissing();
  const issues = state.data.issues.filter((item) => item.topicId === topic.id);
  const cards = state.data.cards.filter((item) => topic.relatedCardIds.includes(item.id));
  const research = state.data.research.filter((item) => topic.relatedResearchIds.includes(item.id));
  contentEl.innerHTML = `
    <section class="detail">
      <p class="eyebrow">Topic Detail</p>
      <h3>${escapeHtml(topic.title)}</h3>
      <div class="meta-strip">
        <span>${escapeHtml(topic.id)}</span>
        <span>${escapeHtml(topic.status)}</span>
        <span>${topic.activeIssueIds.length} active issues</span>
        <span>声明 issue 数 ${topic.issueCountDeclared ?? "-"}</span>
      </div>
      <p>这个 Topic 下可以直接跳到 Issue 详情；如果站内已有关联的 merged card / research，也会在下面一起展示。</p>
    </section>
    <div class="grid">
      <section class="list-panel">
        <p class="eyebrow">Issues</p>
        <h3>Issue 详情入口</h3>
        ${issues.length ? issues.map((item) => assetRow(item, "issue")).join("") : empty("这个 Topic 暂无 issue。")}
      </section>
      <section class="list-panel">
        <p class="eyebrow">Cards & Research</p>
        <h3>相关资产</h3>
        ${cards.map((item) => assetRow(item, "card")).join("") || ""}
        ${research.map((item) => assetRow(item, "research")).join("") || ""}
        ${cards.length || research.length ? "" : empty("当前没有自动匹配到关联 merged card 或 research，请用搜索补充查找。")}
      </section>
    </div>
  `;
}

function renderAssetIndex(kind, items, heading) {
  contentEl.innerHTML = `
    <section class="list-panel">
      <p class="eyebrow">${kind}</p>
      <h3>${heading}</h3>
      ${items.map((item) => assetRow(item, item.type === "research" ? "research" : item.type)).join("")}
    </section>
  `;
}

function renderAssetDetail(item, label) {
  if (!item) return renderMissing();
  const topic = item.topicId ? state.data.topics.find((row) => row.id === item.topicId) : null;
  contentEl.innerHTML = `
    <section class="detail">
      <p class="eyebrow">${escapeHtml(label)}</p>
      <h3>${escapeHtml(item.title)}</h3>
      <div class="meta-strip">
        <span>${escapeHtml(item.id)}</span>
        ${item.status ? `<span>${escapeHtml(item.status)}</span>` : ""}
        ${item.topicId ? `<span>topic ${escapeHtml(item.topicId)}</span>` : ""}
        ${item.updatedAt ? `<span>updated ${escapeHtml(item.updatedAt)}</span>` : `<span>mtime ${escapeHtml(formatTime(item.mtime))}</span>`}
        ${item.sourceArticleCount ? `<span>${item.sourceArticleCount} source articles</span>` : ""}
      </div>
      ${
        item.canonicalQuestion
          ? `<p><strong>Canonical Question:</strong> ${escapeHtml(item.canonicalQuestion)}</p>`
          : ""
      }
      ${
        topic
          ? `<p><a class="pill" href="#topic/${topic.id}">回到 Topic：${escapeHtml(topic.title)}</a></p>`
          : ""
      }
      <article>${item.html}</article>
    </section>
  `;
}

function renderArticleDetail(item) {
  if (!item) return renderMissing();
  contentEl.innerHTML = `
    <section class="detail">
      <p class="eyebrow">Article</p>
      <h3>${escapeHtml(item.title)}</h3>
      <div class="meta-strip">
        <span>${escapeHtml(item.id)}</span>
        ${item.status ? `<span>${escapeHtml(item.status)}</span>` : ""}
        ${item.sourceId ? `<span>${escapeHtml(item.sourceId)}</span>` : ""}
        ${item.publishedAt ? `<span>published ${escapeHtml(formatTime(item.publishedAt))}</span>` : ""}
        ${item.updatedAt ? `<span>updated ${escapeHtml(formatTime(item.updatedAt))}</span>` : ""}
      </div>
      ${
        item.summary
          ? `<p>${escapeHtml(item.summary)}</p>`
          : `<p>当前 article 未提供 summary，可根据原始来源继续追溯。</p>`
      }
      <div class="pill-row">
        ${
          item.url
            ? `<a class="pill" href="${escapeHtml(item.url)}" target="_blank" rel="noreferrer">打开原始链接</a>`
            : ""
        }
        ${
          item.path
            ? `<span class="pill">本地路径：${escapeHtml(item.path)}</span>`
            : ""
        }
      </div>
    </section>
  `;
}

function renderTimeline() {
  contentEl.innerHTML = `
    <section class="list-panel">
      <p class="eyebrow">Timeline</p>
      <h3>按更新时间排序</h3>
      ${state.data.timeline.map(timelineRow).join("")}
    </section>
  `;
}

function renderMissing() {
  contentEl.innerHTML = empty("没有找到对应资产。请回到侧边栏或搜索框继续查找。");
}

function topicCard(topic) {
  return `
    <a class="list-link" href="#topic/${topic.id}">
      <strong>${escapeHtml(topic.title)}</strong>
      <span>${escapeHtml(topic.id)} · ${topic.activeIssueIds.length} active · ${topic.issueCountDeclared ?? "-"} declared</span>
    </a>
  `;
}

function assetRow(item, routeType) {
  const route = routeType === "research" ? "researchpack" : routeType;
  return `
    <a class="list-link" href="#${route}/${item.id}">
      <strong>${escapeHtml(item.title)}</strong>
      <span>${escapeHtml(item.id)} · ${escapeHtml(item.status || item.type)} · ${escapeHtml((item.canonicalQuestion || "").slice(0, 120))}</span>
    </a>
  `;
}

function timelineRow(item) {
  const route = searchRoute(item);
  return `
    <a class="list-link" href="#${route}/${item.id}">
      <strong>${escapeHtml(item.title)}</strong>
      <span>${escapeHtml(item.type)} · ${escapeHtml(formatTime(item.updatedAt))}</span>
    </a>
  `;
}

function searchDocument(item) {
  const parts = [item.title, item.id];
  if (item.type === "topic") {
    parts.push(item.status || "");
    parts.push(...(item.activeIssueIds || []));
    parts.push(...(item.relatedCardIds || []));
    parts.push(...(item.relatedResearchIds || []));
  } else if (item.type === "article") {
    parts.push(item.summary || "");
    parts.push(item.sourceId || "");
    parts.push(item.url || "");
  } else {
    parts.push(item.canonicalQuestion || "");
    parts.push(item.text || "");
  }
  return parts.join(" ").toLowerCase();
}

function searchScore(item, query) {
  const title = (item.title || "").toLowerCase();
  const id = (item.id || "").toLowerCase();
  const canonicalQuestion = (item.canonicalQuestion || "").toLowerCase();
  const summary = (item.summary || "").toLowerCase();
  const text = (item.text || "").toLowerCase();
  const document = searchDocument(item);

  if (!document.includes(query)) {
    return 0;
  }

  let score = typePriority(item.type);
  if (title === query) score += 200;
  if (title.includes(query)) score += 120;
  if (id === query) score += 100;
  if (id.includes(query)) score += 80;
  if (canonicalQuestion.includes(query)) score += 60;
  if (summary.includes(query)) score += 40;
  if (text.includes(query)) score += 20;
  return score;
}

function searchSnippetText(item) {
  if (item.type === "topic") {
    return [item.title, item.status || "", ...(item.activeIssueIds || [])].join(" ");
  }
  if (item.type === "article") {
    return [item.summary || "", item.sourceId || ""].join(" ");
  }
  return item.text || item.canonicalQuestion || item.title || "";
}

function searchRoute(item) {
  return item.type === "research" ? "researchpack" : item.type;
}

function typePriority(type) {
  switch (type) {
    case "card":
      return 8;
    case "research":
      return 7;
    case "article":
      return 6;
    case "topic":
      return 5;
    case "issue":
      return 4;
    default:
      return 0;
  }
}

function empty(text) {
  return `<div class="empty">${escapeHtml(text)}</div>`;
}

function formatTime(value) {
  if (!value) return "-";
  return new Date(value).toLocaleString("zh-CN", { hour12: false });
}

function snippet(text, query) {
  const lower = text.toLowerCase();
  const idx = lower.indexOf(query);
  if (idx < 0) return text.slice(0, 100);
  const start = Math.max(0, idx - 36);
  return text.slice(start, start + 120);
}

function escapeHtml(value) {
  return String(value)
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;");
}

init().catch((error) => {
  contentEl.innerHTML = `<div class="empty">站点初始化失败：${escapeHtml(error.message)}</div>`;
});
