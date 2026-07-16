const TYPE_ALIASES = {
  topic: ["topic", "topics", "专题", "主题"],
  issue: ["issue", "issues", "议题", "问题"],
  card: ["card", "cards", "知识卡", "卡片", "merged card"],
  research: ["research", "researches", "research pack", "研究", "研报", "报告"],
  article: ["article", "articles", "文章", "稿件"],
  news: ["news", "新闻", "资讯", "新闻库"],
};

const TYPE_WEIGHTS = {
  card: 120,
  research: 112,
  issue: 104,
  topic: 96,
  article: 72,
  news: 64,
};

export function searchRoute(item) {
  return item.type;
}

export function searchSnippetText(item) {
  if (item.type === "topic") {
    return [item.title, item.status || "", ...(item.activeIssueIds || [])].join(" ");
  }
  if (item.type === "article") {
    return [item.summary || "", item.sourceId || ""].join(" ");
  }
  if (item.type === "news") {
    return [item.summary || "", item.sourceId || "", item.status || ""].join(" ");
  }
  return item.text || item.canonicalQuestion || item.title || "";
}

export function searchTopMatches(data, rawQuery, limit = 8) {
  const query = normalizeSearchText(rawQuery);
  if (!query) {
    return [];
  }
  return buildSearchPool(data)
    .map((item) => ({ item, score: searchScore(item, query) }))
    .filter(({ score }) => score > 0)
    .sort(compareMatches)
    .slice(0, limit)
    .map(({ item, score }) => ({
      item,
      score,
      snippetText: searchSnippetText(item),
    }));
}

export function searchScore(item, query) {
  const title = normalizeSearchText(item.title);
  const id = normalizeSearchText(item.id);
  const canonicalQuestion = normalizeSearchText(item.canonicalQuestion);
  const summary = normalizeSearchText(item.summary);
  const text = normalizeSearchText(item.text);
  const aliases = typeAliases(item.type);
  const document = [
    title,
    id,
    canonicalQuestion,
    summary,
    text,
    normalizeSearchText(searchSnippetText(item)),
    aliases.join(" "),
  ]
    .filter(Boolean)
    .join(" ");
  const terms = query.split(" ").filter(Boolean);
  const typeAliasExact = aliases.includes(query);

  if (!typeAliasExact && !document.includes(query) && !terms.every((term) => document.includes(term))) {
    return 0;
  }

  let score = TYPE_WEIGHTS[item.type] || 0;
  if (typeAliasExact) score += 340;

  if (title === query) score += 320;
  else if (title.startsWith(query)) score += 250;
  else if (includesWholePhrase(title, query)) score += 190;
  else if (includesAllTerms(title, terms)) score += 145;
  else if (title.includes(query)) score += 70;

  if (id === query) score += 180;
  else if (id.startsWith(query)) score += 135;
  else if (includesWholePhrase(id, query)) score += 90;
  else if (id.includes(query)) score += 40;

  if (canonicalQuestion) {
    if (includesWholePhrase(canonicalQuestion, query)) score += 88;
    else if (includesAllTerms(canonicalQuestion, terms)) score += 54;
    else if (canonicalQuestion.includes(query)) score += 24;
  }

  if (summary) {
    if (includesWholePhrase(summary, query)) score += 44;
    else if (includesAllTerms(summary, terms)) score += 28;
    else if (summary.includes(query)) score += 14;
  }

  if (text) {
    if (includesWholePhrase(text, query)) score += 18;
    else if (includesAllTerms(text, terms)) score += 10;
    else if (text.includes(query)) score += 4;
  }

  if (terms.length > 1 && includesAllTerms(title, terms)) {
    score += 40;
  }

  return score;
}

function buildSearchPool(data) {
  return [
    ...(data.topics || []).map((item) => ({ ...item, type: "topic" })),
    ...(data.issues || []),
    ...(data.cards || []),
    ...(data.research || []),
    ...(data.articles || []),
    ...(data.news || []),
  ];
}

function compareMatches(left, right) {
  if (right.score !== left.score) {
    return right.score - left.score;
  }
  const typeDelta = (TYPE_WEIGHTS[right.item.type] || 0) - (TYPE_WEIGHTS[left.item.type] || 0);
  if (typeDelta !== 0) {
    return typeDelta;
  }
  const rightTime = timestampOf(right.item);
  const leftTime = timestampOf(left.item);
  if (rightTime !== leftTime) {
    return rightTime - leftTime;
  }
  return (left.item.title || "").localeCompare(right.item.title || "", "zh-CN");
}

function timestampOf(item) {
  const value = item.updatedAt || item.publishedAt || item.mtime || "";
  const time = Date.parse(value);
  return Number.isFinite(time) ? time : 0;
}

function typeAliases(type) {
  return (TYPE_ALIASES[type] || []).map(normalizeSearchText).filter(Boolean);
}

function includesAllTerms(text, terms) {
  return terms.length > 0 && terms.every((term) => text.includes(term));
}

function includesWholePhrase(text, phrase) {
  if (!phrase) {
    return false;
  }
  if (phrase.includes(" ")) {
    return text.includes(phrase);
  }
  return (` ${text} `).includes(` ${phrase} `);
}

function normalizeSearchText(value) {
  return String(value || "")
    .toLowerCase()
    .replace(/[^\p{L}\p{N}]+/gu, " ")
    .trim()
    .replace(/\s+/g, " ");
}
