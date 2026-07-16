import fs from "node:fs";
import path from "node:path";
import { searchTopMatches } from "./search-ranking.mjs";

const root = path.resolve(import.meta.dirname, "..");
const raw = JSON.parse(fs.readFileSync(path.join(root, "data/site-data.json"), "utf8"));
const collections = raw.collections || {};
const data = {
  topics: collections.topics || raw.topics || [],
  issues: collections.issues || raw.issues || [],
  cards: collections.cards || raw.cards || [],
  research: collections.research || raw.research || [],
  articles: collections.articles || raw.articles || [],
};

const cases = [
  {
    query: "research",
    assert: (matches) =>
      matches[0]?.item.type === "research" &&
      matches.slice(0, 3).every((match) => match.item.type === "research"),
    reason: "Exact research type query should prioritize research assets over article substrings.",
  },
  {
    query: "topic",
    assert: (matches) =>
      matches[0]?.item.type === "topic" &&
      matches.slice(0, 3).every((match) => match.item.type === "topic"),
    reason: "Exact topic type query should prioritize topic assets.",
  },
  {
    query: "华为",
    assert: (matches) =>
      matches[0]?.item.type === "research" &&
      matches[0]?.item.id === "ai_cloud_value_reconstruction_20260612",
    reason: "Curated Huawei research should rank above raw article mentions.",
  },
  {
    query: "git",
    assert: (matches) => matches[0]?.item.id === "ic_coding_agent_git_governance_rollback",
    reason: "Direct title hit for Git governance card should be the top result.",
  },
];

const failures = [];
for (const testCase of cases) {
  const matches = searchTopMatches(data, testCase.query, 5);
  if (!testCase.assert(matches)) {
    failures.push({
      query: testCase.query,
      reason: testCase.reason,
      observed: matches.map((match) => ({
        type: match.item.type,
        id: match.item.id,
        title: match.item.title,
        score: match.score,
      })),
    });
  }
}

if (failures.length) {
  console.error(JSON.stringify({ status: "failed", failures }, null, 2));
  process.exit(1);
}

console.log(
  JSON.stringify(
    {
      status: "passed",
      cases: cases.map((testCase) => ({
        query: testCase.query,
        top: searchTopMatches(data, testCase.query, 3).map((match) => ({
          type: match.item.type,
          id: match.item.id,
          title: match.item.title,
          score: match.score,
        })),
      })),
    },
    null,
    2,
  ),
);
