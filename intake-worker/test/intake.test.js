import assert from "node:assert/strict";
import test from "node:test";

import worker, { hasLeadingZeroBits, validateSubmission } from "../src/index.js";

function validSubmission(overrides = {}) {
  return {
    request_id: "req_12345678",
    title: "AI 云推理成本结构研究",
    research_question: "请系统研究 AI 云推理成本结构、关键变量、反例与未来三年变化。",
    reference_notes: "可参考公开财报与产业数据。",
    visibility: "public",
    requester_email: "",
    challenge_id: "CH-1234567890ABCDEF",
    challenge_counter: 42,
    consent: true,
    website: "",
    ...overrides,
  };
}

test("private submission requires email while public email stays optional", () => {
  assert.equal(validateSubmission(validSubmission()).requester_email, "");
  assert.throws(
    () => validateSubmission(validSubmission({ visibility: "private" })),
    /私密课题必须填写有效邮箱/,
  );
  assert.equal(
    validateSubmission(validSubmission({ visibility: "private", requester_email: "Owner@Example.com" })).requester_email,
    "owner@example.com",
  );
});

test("payload length, consent and honeypot are enforced", () => {
  assert.throws(() => validateSubmission(validSubmission({ title: "短" })), /课题标题/);
  assert.throws(() => validateSubmission(validSubmission({ consent: false })), /确认提交/);
  assert.throws(() => validateSubmission(validSubmission({ website: "https://spam.example" })), /安全校验/);
});

test("proof-of-work leading bit check is exact", () => {
  assert.equal(hasLeadingZeroBits("000ffffffff", 12), true);
  assert.equal(hasLeadingZeroBits("001ffffffff", 12), false);
  assert.equal(hasLeadingZeroBits("07fffffffff", 5), true);
  assert.equal(hasLeadingZeroBits("08fffffffff", 5), false);
});

test("unknown origin is rejected before storage is used", async () => {
  const response = await worker.fetch(
    new Request("https://worker.example/v1/challenge", { headers: { Origin: "https://evil.example" } }),
    { ALLOWED_ORIGINS: "https://searchbb.github.io", RATE_SALT: "test-secret" },
  );
  assert.equal(response.status, 403);
  assert.equal((await response.json()).error, "origin_not_allowed");
});

test("private pull endpoint fails closed without bearer secret", async () => {
  const response = await worker.fetch(
    new Request("https://worker.example/v1/claims/pull", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ limit: 1 }),
    }),
    { DB: {}, ALLOWED_ORIGINS: "https://searchbb.github.io" },
  );
  assert.equal(response.status, 401);
  assert.equal((await response.json()).error, "unauthorized");
});
