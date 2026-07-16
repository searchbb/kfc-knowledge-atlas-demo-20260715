const state = {
  data: null,
  timelineType: "all",
  timelineEvent: "all",
  mermaid: null,
  fastDetail: null,
  detailCache: new Map(),
  indexLoadId: 0,
  searchBound: false,
  searchTools: null,
  searchReadyPromise: null,
  loadedRoutes: new Set(),
};
const contentEl = document.getElementById("content");
const statsEl = document.getElementById("stats");
const topicNavEl = document.getElementById("topic-nav");
const searchInput = document.getElementById("search-input");
const searchResults = document.getElementById("search-results");
const RESEARCH_INTAKE = window.KFC_RESEARCH_INTAKE || {};

const ROUTES = {
  topic: "topics",
  issue: "issues",
  card: "cards",
  research: "research",
  article: "articles",
  news: "news",
};

function routeParts() {
  const [route, encodedId] = (window.location.hash.replace(/^#/, "") || "home").split("/");
  return { route, id: decodeURIComponent(encodedId || "") };
}

function updateRouteMode() {
  const { route, id } = routeParts();
  document.documentElement.classList.toggle("direct-detail", Boolean(id && Object.hasOwn(ROUTES, route)));
}

function emptyPortalData(type, item) {
  const data = {
    stats: {}, newsMeta: {}, relations: [], timeline: [],
    topics: [], issues: [], cards: [], research: [], articles: [], news: [],
  };
  data[ROUTES[type]] = [item];
  return data;
}

async function loadFastDetail() {
  const { route, id } = routeParts();
  if (!id || !Object.hasOwn(ROUTES, route)) return null;
  if (window.__fastDetailPromise) {
    const bootstrapped = await window.__fastDetailPromise;
    if (bootstrapped?.type === route && bootstrapped?.id === id && bootstrapped.item) return bootstrapped;
  }
  const payload = await fetchJson(`./data/details/${route}/${encodeURIComponent(id)}.json`);
  if (payload.type !== route || payload.id !== id || !payload.item) return null;
  return { type: route, id, item: payload.item };
}

async function fetchJson(url, { timeoutMs = 10000 } = {}) {
  const controller = new AbortController();
  const timeout = window.setTimeout(() => controller.abort(), timeoutMs);
  try {
    const response = await fetch(url, { cache: "default", signal: controller.signal });
    if (!response.ok) throw new Error(`数据加载失败（${response.status}）`);
    return await response.json();
  } catch (error) {
    if (error.name === "AbortError") throw new Error("网络响应超时");
    throw error;
  } finally {
    window.clearTimeout(timeout);
  }
}

function emptyData() {
  return normalizeData({ collections: {} });
}

function mergeData(raw) {
  const incoming = normalizeData(raw);
  if (!state.data) state.data = emptyData();
  for (const name of ["topics", "issues", "cards", "research", "articles", "news"]) {
    if (Object.hasOwn(raw.collections || raw, name)) state.data[name] = incoming[name];
  }
  for (const name of ["stats", "newsMeta", "relations", "timeline", "buildMeta", "generatedAt"]) {
    if (Object.hasOwn(raw, name)) state.data[name] = incoming[name];
  }
  return state.data;
}

function routeDataUrl(route) {
  if (route === "home" || route === "timeline" || Object.values(ROUTES).includes(route)) {
    return `./data/route-${route}.json`;
  }
  return "";
}

async function init() {
  state.data = emptyData();
  bindSearch();
  state.searchBound = true;
  searchInput.disabled = false;
  updateRouteMode();
  window.addEventListener("hashchange", () => {
    updateRouteMode();
    void renderRoute();
  });
  state.fastDetail = await loadFastDetail();
  const { route, id } = routeParts();
  const homeBootstrap = !id && route === "home"
    ? contentEl.querySelector("[data-home-bootstrap]")
    : null;
  if (state.fastDetail) {
    state.detailCache.set(`${state.fastDetail.type}/${state.fastDetail.id}`, state.fastDetail.item);
    state.data = emptyPortalData(state.fastDetail.type, state.fastDetail.item);
    setActiveNav(state.fastDetail.type);
    renderDetail(state.fastDetail.type, state.fastDetail.item);
  } else if (!homeBootstrap) {
    renderPortalLoading();
  }
  if (homeBootstrap) {
    statsEl.hidden = false;
    setActiveNav("home");
    void hydrateHomeBootstrap(homeBootstrap.dataset.generatedAt || "");
  } else if (!state.fastDetail) {
    await renderRoute();
  }
}

async function hydrateHomeBootstrap(embeddedGeneratedAt) {
  const loadId = ++state.indexLoadId;
  try {
    const data = await fetchJson("./data/route-home.json", { timeoutMs: 30000 });
    if (loadId !== state.indexLoadId) return;
    mergeData(data);
    state.loadedRoutes.add("home");
    renderStats();
    renderTopicNav();
    const current = routeParts();
    if (current.route === "home" && !current.id) renderHome();
    if (embeddedGeneratedAt && data.generatedAt !== embeddedGeneratedAt) {
      document.documentElement.dataset.homeRefreshed = "true";
    }
  } catch (error) {
    // 静态首页已经可读；后台刷新失败时保留内容，不降级为错误页。
    searchInput.placeholder = "当前显示最近快照，可继续浏览";
  }
}

async function ensureRouteData(route) {
  const url = routeDataUrl(route);
  if (!url || state.loadedRoutes.has(route)) return true;
  const loadId = ++state.indexLoadId;
  renderPortalLoading();
  const slowTimer = window.setTimeout(showSlowLoadingNote, 2500);
  try {
    // GitHub Pages 在部分手机网络上偶发连接握手抖动；骨架持续可见，
    // 不要在小路由数据仍可能成功时过早把页面判成失败。
    const data = await fetchJson(url, { timeoutMs: 30000 });
    if (loadId !== state.indexLoadId) return;
    mergeData(data);
    state.loadedRoutes.add(route);
    if (route === "home") renderStats();
    if (route === "home" || route === "topics") renderTopicNav();
    return true;
  } catch (error) {
    if (loadId !== state.indexLoadId) return;
    renderLoadError(error, () => void renderRoute());
    return false;
  } finally {
    window.clearTimeout(slowTimer);
  }
}

function loadingSkeleton(label = "最新内容") {
  return `<section class="portal-loading" aria-live="polite">
    <p class="eyebrow">${escapeHtml(label)}</p>
    <div class="skeleton-line skeleton-title"></div>
    <div class="skeleton-line skeleton-copy"></div>
    <div class="skeleton-line skeleton-copy short"></div>
    <div class="skeleton-list">${Array.from({ length: 5 }, () => '<div class="skeleton-line skeleton-row"></div>').join("")}</div>
    <p class="loading-note" hidden>正在加载最新内容…</p>
  </section>`;
}

function renderPortalLoading() {
  if (!contentEl.querySelector(".portal-loading")) contentEl.innerHTML = loadingSkeleton();
}

function showSlowLoadingNote() {
  contentEl.querySelector(".loading-note")?.removeAttribute("hidden");
}

function renderLoadError(error, retry) {
  contentEl.innerHTML = `<section class="load-error" role="alert">
    <p class="eyebrow">连接提示</p>
    <h3>内容加载失败</h3>
    <p>${escapeHtml(error.message || "网络暂时不可用")}</p>
    <button class="retry-button" type="button">重新加载</button>
  </section>`;
  contentEl.querySelector(".retry-button")?.addEventListener("click", retry);
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
  searchInput.addEventListener("input", async () => {
    const query = searchInput.value.trim();
    if (!query) return (searchResults.innerHTML = "");
    if (!state.searchTools) {
      searchResults.innerHTML = '<div class="search-hit"><span>正在准备搜索…</span></div>';
      try {
        if (!state.searchReadyPromise) {
          state.searchReadyPromise = Promise.all([
            fetchJson("./data/site-index.json", { timeoutMs: 30000 }),
            import("./scripts/search-ranking.mjs"),
          ]);
        }
        const [fullIndex, tools] = await state.searchReadyPromise;
        mergeData(fullIndex);
        state.searchTools = tools;
      } catch (error) {
        state.searchReadyPromise = null;
        searchResults.innerHTML = `<div class="search-hit"><span>搜索数据加载失败，请稍后重试</span></div>`;
        return;
      }
      if (searchInput.value.trim() !== query) return;
    }
    const { searchRoute, searchTopMatches } = state.searchTools;
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
  statsEl.innerHTML = `
    <p class="stats-title">内容规模</p>
    ${rows.map(([label, value]) => `
      <div class="stat">
        <p>${label}</p><strong>${Number(value || 0).toLocaleString("zh-CN")}</strong>
      </div>`).join("")}`;
}

function renderTopicNav() {
  topicNavEl.innerHTML = state.data.topics.map((topic) => `
    <a class="topic-link" href="${routeHref("topic", topic.id)}">
      <strong>${escapeHtml(topic.title)}</strong>
      <div class="meta-strip"><span>${escapeHtml(statusLabel(topic.status))}</span><span>${topic.activeIssueIds.length} 个议题</span></div>
    </a>`).join("");
}

async function renderRoute() {
  searchResults.innerHTML = "";
  updateRouteMode();
  const { route, id } = routeParts();
  statsEl.hidden = route !== "home";
  setActiveNav(route);
  if (id && Object.hasOwn(ROUTES, route)) return renderDetailRoute(route, id);
  const ready = await ensureRouteData(route);
  if (!ready) return;
  if (route === "home") return renderHome();
  if (route === "timeline") return renderTimeline();
  if (Object.values(ROUTES).includes(route)) return renderAssetIndex(route, state.data[route]);
  renderMissing();
}

async function loadDetailItem(type, id) {
  const key = `${type}/${id}`;
  if (state.detailCache.has(key)) return state.detailCache.get(key);
  const payload = await fetchJson(`./data/details/${type}/${encodeURIComponent(id)}.json`);
  if (payload.type !== type || payload.id !== id || !payload.item) {
    throw new Error("详情数据格式不完整");
  }
  state.detailCache.set(key, payload.item);
  return payload.item;
}

async function renderDetailRoute(type, id) {
  const expectedRoute = `${type}/${id}`;
  const cached = state.detailCache.get(expectedRoute);
  if (cached) return renderDetail(type, cached);
  const preview = entity(type, id);
  contentEl.innerHTML = `<section class="detail detail-header detail-loading">
    <p class="eyebrow">${escapeHtml(typeLabel(type))}</p>
    <h3>${escapeHtml(preview?.title || "正在打开内容")}</h3>
    ${loadingSkeleton("内容正文")}
  </section>`;
  const slowTimer = window.setTimeout(showSlowLoadingNote, 2500);
  try {
    const item = await loadDetailItem(type, id);
    const current = routeParts();
    if (`${current.route}/${current.id}` !== expectedRoute) return;
    renderDetail(type, item);
  } catch (error) {
    const current = routeParts();
    if (`${current.route}/${current.id}` !== expectedRoute) return;
    renderLoadError(error, () => void renderDetailRoute(type, id));
  } finally {
    window.clearTimeout(slowTimer);
  }
}

function setActiveNav(route) {
  const listRoute = ROUTES[route] || route;
  document.querySelectorAll(".nav a").forEach((link) => {
    const active = link.getAttribute("href") === `#${listRoute}`;
    link.classList.toggle("active", active);
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
  contentEl.innerHTML = `${kind === "research" ? renderResearchIntake() : ""}<section class="list-panel index-page"><div class="section-heading"><div><p class="eyebrow">${typeLabel(kind)}</p><h3>${typeLabel(kind)} <small>${countLabel}</small></h3></div></div><p class="index-intro">${intro}</p>${rows || empty("暂无内容。")}</section>`;
  if (kind === "research") bindResearchIntake();
}

function renderResearchIntake() {
  const endpointReady = /^https:\/\//.test(String(RESEARCH_INTAKE.endpoint || ""));
  return `<section class="research-intake" aria-labelledby="research-intake-title">
    <div class="research-intake-heading">
      <div><p class="eyebrow">研究课题征集</p><h3 id="research-intake-title">提交一个深度研究课题</h3></div>
      <span class="intake-sla">目标 60 分钟内形成报告</span>
    </div>
    <p class="research-intake-lead">直接在这里写下想研究的问题、参考资料和交付方式。提交后会获得回执编号；课题进入独立研究队列，由本地 Research Pack 流程领取。</p>
    <form id="research-intake-form" class="research-intake-form" novalidate>
      <label class="form-field form-field-wide">
        <span>课题标题 <b>*</b></span>
        <input name="title" minlength="4" maxlength="120" required placeholder="例如：AI 云推理成本结构与竞争壁垒" />
      </label>
      <label class="form-field form-field-wide">
        <span>核心研究问题 <b>*</b></span>
        <textarea name="research_question" minlength="20" maxlength="6000" required rows="6" placeholder="希望回答什么问题？范围、时间跨度、地区、重点公司或反例是什么？"></textarea>
      </label>
      <label class="form-field form-field-wide">
        <span>参考资料与补充提示</span>
        <textarea name="reference_notes" maxlength="4000" rows="3" placeholder="可粘贴公开链接、已知事实、希望重点验证的判断；没有可留空。"></textarea>
      </label>
      <fieldset class="form-field delivery-choice">
        <legend>交付方式 <b>*</b></legend>
        <label><input type="radio" name="visibility" value="public" checked /> 公开报告</label>
        <label><input type="radio" name="visibility" value="private" /> 私密报告</label>
        <small id="visibility-help">公开报告完成后会进入本站“深度研究”；邮箱可选。</small>
      </fieldset>
      <label class="form-field">
        <span>接收邮箱 <b id="email-required" hidden>*</b></span>
        <input name="requester_email" type="email" maxlength="254" autocomplete="email" placeholder="私密报告必须填写" />
        <small>私密报告只通过此邮箱交付，不在网站公开。</small>
      </label>
      <label class="form-field website-field" aria-hidden="true">
        <span>Website</span><input name="website" tabindex="-1" autocomplete="off" />
      </label>
      <label class="consent-field form-field-wide">
        <input name="consent" type="checkbox" required />
        <span>我确认课题不包含密码、个人敏感信息或无权提交的保密材料，并理解一小时是目标时限，复杂课题可能排队或要求补充资料。</span>
      </label>
      <div class="research-intake-actions form-field-wide">
        <button type="submit" class="research-submit" ${endpointReady ? "" : "disabled"}>${endpointReady ? "提交研究课题" : "提交入口正在接通"}</button>
        <p id="research-intake-status" class="research-intake-status" role="status" aria-live="polite">${endpointReady ? "提交后请保存回执编号。" : "接收服务部署完成后，此处将直接开放，无需跳转到其他网站。"}</p>
      </div>
    </form>
  </section>`;
}

function leadingZeroBits(hex, difficulty) {
  const wholeNibbles = Math.floor(difficulty / 4);
  const remainder = difficulty % 4;
  if (!hex.startsWith("0".repeat(wholeNibbles))) return false;
  if (!remainder) return true;
  return Number.parseInt(hex[wholeNibbles], 16) < (1 << (4 - remainder));
}

async function sha256Hex(value) {
  const bytes = await crypto.subtle.digest("SHA-256", new TextEncoder().encode(value));
  return [...new Uint8Array(bytes)].map((item) => item.toString(16).padStart(2, "0")).join("");
}

async function solveResearchChallenge(challenge) {
  const difficulty = Number(challenge.difficulty || 12);
  for (let counter = 0; counter < 5_000_000; counter += 1) {
    const digest = await sha256Hex(`${challenge.nonce}:${counter}`);
    if (leadingZeroBits(digest, difficulty)) return counter;
    if (counter > 0 && counter % 500 === 0) await new Promise((resolve) => setTimeout(resolve, 0));
  }
  throw new Error("安全校验计算超时，请稍后重试。");
}

async function intakeFetch(path, options = {}) {
  const endpoint = String(RESEARCH_INTAKE.endpoint || "").replace(/\/$/, "");
  const response = await fetch(`${endpoint}${path}`, { ...options, cache: "no-store" });
  const payload = await response.json().catch(() => ({}));
  if (!response.ok) throw new Error(payload.message || `提交失败（${response.status}）`);
  return payload;
}

function bindResearchIntake() {
  const form = document.getElementById("research-intake-form");
  if (!form) return;
  const email = form.elements.requester_email;
  const emailRequired = document.getElementById("email-required");
  const help = document.getElementById("visibility-help");
  const status = document.getElementById("research-intake-status");
  const submit = form.querySelector("button[type=submit]");
  const syncVisibility = () => {
    const isPrivate = form.elements.visibility.value === "private";
    email.required = isPrivate;
    emailRequired.hidden = !isPrivate;
    help.textContent = isPrivate
      ? "私密报告不会出现在网站，必须填写邮箱接收终稿。"
      : "公开报告完成后会进入本站“深度研究”；邮箱可选。";
  };
  form.querySelectorAll('input[name="visibility"]').forEach((input) => input.addEventListener("change", syncVisibility));
  syncVisibility();
  if (!/^https:\/\//.test(String(RESEARCH_INTAKE.endpoint || ""))) return;
  form.addEventListener("submit", async (event) => {
    event.preventDefault();
    if (!form.reportValidity()) return;
    const requestId = form.dataset.requestId || crypto.randomUUID();
    form.dataset.requestId = requestId;
    submit.disabled = true;
    submit.textContent = "正在进行安全校验…";
    status.className = "research-intake-status";
    status.textContent = "正在准备提交，请不要关闭页面。";
    try {
      const challenge = await intakeFetch("/v1/challenge");
      const counter = await solveResearchChallenge(challenge);
      submit.textContent = "正在写入研究队列…";
      const values = new FormData(form);
      const payload = await intakeFetch("/v1/submissions", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          request_id: requestId,
          title: values.get("title"),
          research_question: values.get("research_question"),
          reference_notes: values.get("reference_notes"),
          visibility: values.get("visibility"),
          requester_email: values.get("requester_email"),
          website: values.get("website"),
          consent: values.get("consent") === "on",
          challenge_id: challenge.challenge_id,
          challenge_counter: counter,
        }),
      });
      status.className = "research-intake-status success";
      status.innerHTML = `已进入研究队列。回执编号：<strong>${escapeHtml(payload.receipt_id)}</strong>。请保存此编号；目标在 ${Number(payload.target_minutes || RESEARCH_INTAKE.targetMinutes || 60)} 分钟内形成结果。`;
      submit.textContent = "已提交";
      localStorage.setItem("kfc-last-research-receipt", payload.receipt_id);
    } catch (error) {
      status.className = "research-intake-status error";
      status.textContent = error.message || "提交失败，请稍后重试。";
      submit.disabled = false;
      submit.textContent = "重新提交";
    }
  });
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

init().catch((error) => renderLoadError(error, () => void init()));
