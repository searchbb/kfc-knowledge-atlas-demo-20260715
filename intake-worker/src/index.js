const EMAIL_PATTERN = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;
const REQUEST_ID_PATTERN = /^[a-zA-Z0-9][a-zA-Z0-9_-]{7,79}$/;
const RECEIPT_PATTERN = /^RQ-[A-Z0-9]{16}$/;

export class HttpError extends Error {
  constructor(status, code, message) {
    super(message);
    this.status = status;
    this.code = code;
  }
}

function nowIso() {
  return new Date().toISOString();
}

function futureIso(seconds) {
  return new Date(Date.now() + seconds * 1000).toISOString();
}

function allowedOrigins(env) {
  return new Set(String(env.ALLOWED_ORIGINS || "")
    .split(",")
    .map((value) => value.trim())
    .filter(Boolean));
}

function requestOrigin(request) {
  return request.headers.get("Origin") || "";
}

function assertAllowedOrigin(request, env) {
  const origin = requestOrigin(request);
  if (!origin || !allowedOrigins(env).has(origin)) {
    throw new HttpError(403, "origin_not_allowed", "该提交来源未获授权。请从正式研究页面提交。");
  }
  return origin;
}

function corsHeaders(origin, env) {
  if (!origin || !allowedOrigins(env).has(origin)) return {};
  return {
    "Access-Control-Allow-Origin": origin,
    "Access-Control-Allow-Headers": "Content-Type, Authorization",
    "Access-Control-Allow-Methods": "GET, POST, DELETE, OPTIONS",
    "Access-Control-Max-Age": "86400",
    "Vary": "Origin",
  };
}

function json(payload, { status = 200, origin = "", env = {} } = {}) {
  return new Response(JSON.stringify(payload), {
    status,
    headers: {
      "Content-Type": "application/json; charset=utf-8",
      "Cache-Control": "no-store",
      "X-Content-Type-Options": "nosniff",
      ...corsHeaders(origin, env),
    },
  });
}

function cleanText(value) {
  return String(value ?? "").replace(/\u0000/g, "").trim();
}

export function validateSubmission(raw) {
  const submission = {
    request_id: cleanText(raw.request_id),
    title: cleanText(raw.title),
    research_question: cleanText(raw.research_question),
    reference_notes: cleanText(raw.reference_notes),
    visibility: cleanText(raw.visibility),
    requester_email: cleanText(raw.requester_email).toLowerCase(),
    challenge_id: cleanText(raw.challenge_id),
    challenge_counter: Number(raw.challenge_counter),
    consent: raw.consent === true,
    website: cleanText(raw.website),
  };
  if (!REQUEST_ID_PATTERN.test(submission.request_id)) {
    throw new HttpError(400, "request_id_invalid", "请求编号格式不正确，请刷新页面后重试。");
  }
  if (submission.title.length < 4 || submission.title.length > 120) {
    throw new HttpError(400, "title_invalid", "课题标题需为 4 到 120 个字符。");
  }
  if (submission.research_question.length < 20 || submission.research_question.length > 6000) {
    throw new HttpError(400, "question_invalid", "研究问题需为 20 到 6000 个字符。");
  }
  if (submission.reference_notes.length > 4000) {
    throw new HttpError(400, "references_too_long", "参考资料与提示不能超过 4000 个字符。");
  }
  if (!new Set(["public", "private"]).has(submission.visibility)) {
    throw new HttpError(400, "visibility_invalid", "请选择公开或私密交付。");
  }
  if (submission.visibility === "private" && !EMAIL_PATTERN.test(submission.requester_email)) {
    throw new HttpError(400, "private_email_required", "私密课题必须填写有效邮箱。");
  }
  if (submission.requester_email && !EMAIL_PATTERN.test(submission.requester_email)) {
    throw new HttpError(400, "email_invalid", "邮箱格式不正确。");
  }
  if (!submission.consent) {
    throw new HttpError(400, "consent_required", "请确认提交与交付规则。");
  }
  if (submission.website) {
    throw new HttpError(400, "spam_rejected", "提交未通过安全校验。");
  }
  if (!/^CH-[A-Z0-9]{16}$/.test(submission.challenge_id)
      || !Number.isSafeInteger(submission.challenge_counter)
      || submission.challenge_counter < 0) {
    throw new HttpError(400, "challenge_invalid", "安全校验已失效，请重新提交。");
  }
  return submission;
}

function randomToken(prefix) {
  return `${prefix}-${crypto.randomUUID().replaceAll("-", "").slice(0, 16).toUpperCase()}`;
}

function bytesToHex(bytes) {
  return [...new Uint8Array(bytes)].map((value) => value.toString(16).padStart(2, "0")).join("");
}

async function hmacHex(secret, value) {
  if (!secret) throw new HttpError(503, "service_not_configured", "提交服务尚未完成安全配置。");
  const key = await crypto.subtle.importKey(
    "raw",
    new TextEncoder().encode(secret),
    { name: "HMAC", hash: "SHA-256" },
    false,
    ["sign"],
  );
  return bytesToHex(await crypto.subtle.sign("HMAC", key, new TextEncoder().encode(value)));
}

async function hashHex(value) {
  return bytesToHex(await crypto.subtle.digest("SHA-256", new TextEncoder().encode(value)));
}

export function hasLeadingZeroBits(hex, difficulty) {
  const wholeNibbles = Math.floor(difficulty / 4);
  const remainder = difficulty % 4;
  if (!hex.startsWith("0".repeat(wholeNibbles))) return false;
  if (!remainder) return true;
  const nibble = Number.parseInt(hex[wholeNibbles], 16);
  return nibble < (1 << (4 - remainder));
}

async function parseJson(request) {
  const contentLength = Number(request.headers.get("Content-Length") || 0);
  if (contentLength > 20_000) throw new HttpError(413, "payload_too_large", "提交内容过长。");
  if (!String(request.headers.get("Content-Type") || "").toLowerCase().startsWith("application/json")) {
    throw new HttpError(415, "json_required", "提交必须使用 JSON 格式。");
  }
  try {
    return await request.json();
  } catch {
    throw new HttpError(400, "json_invalid", "提交内容格式不正确。");
  }
}

function clientIp(request, env) {
  const proxySecret = request.headers.get("X-Intake-Proxy-Secret") || "";
  if (env.PROXY_SHARED_SECRET && proxySecret === env.PROXY_SHARED_SECRET) {
    return request.headers.get("X-Intake-Client-IP") || "unknown";
  }
  return request.headers.get("CF-Connecting-IP") || request.headers.get("X-Test-IP") || "unknown";
}

async function ipHash(request, env) {
  return hmacHex(env.RATE_SALT, clientIp(request, env));
}

async function authorize(request, env) {
  const expected = String(env.MAC_PULL_TOKEN || "");
  const actual = String(request.headers.get("Authorization") || "").replace(/^Bearer\s+/i, "");
  if (!expected || !actual) throw new HttpError(401, "unauthorized", "缺少接收器凭据。");
  const [expectedHash, actualHash] = await Promise.all([hashHex(expected), hashHex(actual)]);
  if (expectedHash !== actualHash) throw new HttpError(401, "unauthorized", "接收器凭据无效。");
}

export class D1Store {
  constructor(db) {
    if (!db) throw new HttpError(503, "service_not_configured", "提交队列尚未连接。");
    this.db = db;
  }

  async countChallenges(ipHashValue, since) {
    const row = await this.db.prepare(
      "SELECT COUNT(*) AS count FROM research_challenges WHERE ip_hash=? AND created_at>=?",
    ).bind(ipHashValue, since).first();
    return Number(row?.count || 0);
  }

  async createChallenge(row) {
    await this.db.prepare(
      "INSERT INTO research_challenges(challenge_id,nonce,difficulty,ip_hash,expires_at,created_at) VALUES(?,?,?,?,?,?)",
    ).bind(row.challenge_id, row.nonce, row.difficulty, row.ip_hash, row.expires_at, row.created_at).run();
  }

  async getChallenge(challengeId) {
    return this.db.prepare("SELECT * FROM research_challenges WHERE challenge_id=?")
      .bind(challengeId).first();
  }

  async consumeChallenge(challengeId, ipHashValue, usedAt) {
    const result = await this.db.prepare(
      "UPDATE research_challenges SET used_at=? WHERE challenge_id=? AND ip_hash=? AND used_at IS NULL AND expires_at>?",
    ).bind(usedAt, challengeId, ipHashValue, usedAt).run();
    return Number(result.meta?.changes || 0) === 1;
  }

  async countSubmissions(ipHashValue, since) {
    const row = await this.db.prepare(
      "SELECT COUNT(*) AS count FROM research_submissions WHERE ip_hash=? AND created_at>=?",
    ).bind(ipHashValue, since).first();
    return Number(row?.count || 0);
  }

  async findByRequestId(requestId) {
    return this.db.prepare("SELECT * FROM research_submissions WHERE request_id=?")
      .bind(requestId).first();
  }

  async insertSubmission(row) {
    await this.db.prepare(
      `INSERT INTO research_submissions(
        receipt_id,request_id,title,research_question,reference_notes,visibility,
        requester_email,ip_hash,status,created_at,updated_at
      ) VALUES(?,?,?,?,?,?,?,?,?,?,?)`,
    ).bind(
      row.receipt_id, row.request_id, row.title, row.research_question,
      row.reference_notes, row.visibility, row.requester_email, row.ip_hash,
      "queued", row.created_at, row.updated_at,
    ).run();
  }

  async getPublicStatus(receiptId) {
    return this.db.prepare(
      "SELECT receipt_id,status,created_at,updated_at FROM research_submissions WHERE receipt_id=?",
    ).bind(receiptId).first();
  }

  async pull(limit) {
    const result = await this.db.prepare(
      `SELECT receipt_id,request_id,title,research_question,reference_notes,visibility,
              requester_email,attempts,created_at
       FROM research_submissions WHERE status='queued'
       ORDER BY created_at ASC LIMIT ?`,
    ).bind(limit).all();
    return result.results || [];
  }

  async ack(receiptId, localJobId, updatedAt) {
    const result = await this.db.prepare(
      `UPDATE research_submissions
       SET status='imported',local_job_id=?,imported_at=?,updated_at=?,last_error=''
       WHERE receipt_id=? AND status IN ('queued','imported')`,
    ).bind(localJobId, updatedAt, updatedAt, receiptId).run();
    return Number(result.meta?.changes || 0) === 1;
  }

  async fail(receiptId, error, retryable, updatedAt) {
    const status = retryable ? "queued" : "blocked";
    const result = await this.db.prepare(
      `UPDATE research_submissions
       SET status=?,attempts=attempts+1,last_error=?,updated_at=?
       WHERE receipt_id=? AND status IN ('queued','blocked')`,
    ).bind(status, error.slice(0, 240), updatedAt, receiptId).run();
    return Number(result.meta?.changes || 0) === 1;
  }

  async remove(receiptId) {
    const result = await this.db.prepare("DELETE FROM research_submissions WHERE receipt_id=?")
      .bind(receiptId).run();
    return Number(result.meta?.changes || 0) === 1;
  }
}

async function challengeResponse(request, env, store) {
  const origin = assertAllowedOrigin(request, env);
  const hashedIp = await ipHash(request, env);
  const since = new Date(Date.now() - 10 * 60 * 1000).toISOString();
  if (await store.countChallenges(hashedIp, since) >= 20) {
    throw new HttpError(429, "challenge_rate_limited", "请求过于频繁，请十分钟后再试。");
  }
  const difficulty = Math.max(8, Math.min(20, Number(env.POW_DIFFICULTY || 12)));
  const row = {
    challenge_id: randomToken("CH"),
    nonce: crypto.randomUUID(),
    difficulty,
    ip_hash: hashedIp,
    expires_at: futureIso(300),
    created_at: nowIso(),
  };
  await store.createChallenge(row);
  return json({
    ok: true,
    challenge_id: row.challenge_id,
    nonce: row.nonce,
    difficulty,
    expires_at: row.expires_at,
  }, { origin, env });
}

async function submissionResponse(request, env, store) {
  const origin = assertAllowedOrigin(request, env);
  const submission = validateSubmission(await parseJson(request));
  const hashedIp = await ipHash(request, env);
  const existing = await store.findByRequestId(submission.request_id);
  if (existing) {
    return json({
      ok: true,
      status: existing.status,
      receipt_id: existing.receipt_id,
      submitted_at: existing.created_at,
      visibility: existing.visibility,
      target_minutes: 60,
      idempotent: true,
    }, { status: 200, origin, env });
  }
  const since = new Date(Date.now() - 60 * 60 * 1000).toISOString();
  const limit = Math.max(1, Math.min(20, Number(env.MAX_SUBMISSIONS_PER_HOUR || 5)));
  if (await store.countSubmissions(hashedIp, since) >= limit) {
    throw new HttpError(429, "submission_rate_limited", "本小时提交次数已达上限，请稍后再试。");
  }
  const challenge = await store.getChallenge(submission.challenge_id);
  if (!challenge || challenge.ip_hash !== hashedIp || challenge.used_at
      || new Date(challenge.expires_at).getTime() <= Date.now()) {
    throw new HttpError(400, "challenge_expired", "安全校验已失效，请重新提交。");
  }
  const digest = await hashHex(`${challenge.nonce}:${submission.challenge_counter}`);
  if (!hasLeadingZeroBits(digest, Number(challenge.difficulty))) {
    throw new HttpError(400, "challenge_failed", "安全校验未通过，请重新提交。");
  }
  const consumedAt = nowIso();
  if (!await store.consumeChallenge(submission.challenge_id, hashedIp, consumedAt)) {
    throw new HttpError(409, "challenge_already_used", "该安全校验已经使用，请重新提交。");
  }
  const row = {
    ...submission,
    receipt_id: randomToken("RQ"),
    ip_hash: hashedIp,
    created_at: consumedAt,
    updated_at: consumedAt,
  };
  try {
    await store.insertSubmission(row);
  } catch (error) {
    const raced = await store.findByRequestId(submission.request_id);
    if (!raced) throw error;
    return json({
      ok: true,
      status: raced.status,
      receipt_id: raced.receipt_id,
      submitted_at: raced.created_at,
      visibility: raced.visibility,
      target_minutes: 60,
      idempotent: true,
    }, { status: 200, origin, env });
  }
  return json({
    ok: true,
    status: "queued",
    receipt_id: row.receipt_id,
    submitted_at: row.created_at,
    visibility: row.visibility,
    target_minutes: 60,
  }, { status: 201, origin, env });
}

async function statusResponse(request, env, store, receiptId) {
  const origin = assertAllowedOrigin(request, env);
  if (!RECEIPT_PATTERN.test(receiptId)) throw new HttpError(404, "not_found", "未找到该回执。");
  const row = await store.getPublicStatus(receiptId);
  if (!row) throw new HttpError(404, "not_found", "未找到该回执。");
  return json({ ok: true, ...row }, { origin, env });
}

async function pullResponse(request, env, store) {
  await authorize(request, env);
  const raw = await parseJson(request);
  const limit = Math.max(1, Math.min(10, Number(raw.limit || 3)));
  const rows = await store.pull(limit);
  return json({ ok: true, submissions: rows });
}

async function ackResponse(request, env, store, receiptId) {
  await authorize(request, env);
  if (!RECEIPT_PATTERN.test(receiptId)) throw new HttpError(404, "not_found", "未找到该回执。");
  const raw = await parseJson(request);
  const localJobId = cleanText(raw.local_job_id);
  if (!localJobId || localJobId.length > 160) throw new HttpError(400, "local_job_id_invalid", "本地任务编号无效。");
  const updated = await store.ack(receiptId, localJobId, nowIso());
  if (!updated) throw new HttpError(404, "not_found", "未找到可确认的回执。");
  return json({ ok: true, receipt_id: receiptId, status: "imported" });
}

async function failResponse(request, env, store, receiptId) {
  await authorize(request, env);
  if (!RECEIPT_PATTERN.test(receiptId)) throw new HttpError(404, "not_found", "未找到该回执。");
  const raw = await parseJson(request);
  const retryable = raw.retryable !== false;
  const reason = cleanText(raw.reason) || "local_import_failed";
  const updated = await store.fail(receiptId, reason, retryable, nowIso());
  if (!updated) throw new HttpError(404, "not_found", "未找到可回写的回执。");
  return json({ ok: true, receipt_id: receiptId, status: retryable ? "queued" : "blocked" });
}

export async function handleRequest(request, env, store = null) {
  const url = new URL(request.url);
  const origin = requestOrigin(request);
  if (request.method === "OPTIONS") {
    assertAllowedOrigin(request, env);
    return new Response(null, { status: 204, headers: corsHeaders(origin, env) });
  }
  const browserRoute = (
    (request.method === "GET" && url.pathname === "/v1/challenge")
    || (request.method === "POST" && url.pathname === "/v1/submissions")
    || (request.method === "GET" && /^\/v1\/submissions\/RQ-[A-Z0-9]{16}\/status$/.test(url.pathname))
  );
  if (browserRoute) assertAllowedOrigin(request, env);
  const resolvedStore = store || new D1Store(env.DB);
  if (request.method === "GET" && url.pathname === "/v1/challenge") {
    return challengeResponse(request, env, resolvedStore);
  }
  if (request.method === "POST" && url.pathname === "/v1/submissions") {
    return submissionResponse(request, env, resolvedStore);
  }
  const statusMatch = url.pathname.match(/^\/v1\/submissions\/(RQ-[A-Z0-9]{16})\/status$/);
  if (request.method === "GET" && statusMatch) {
    return statusResponse(request, env, resolvedStore, statusMatch[1]);
  }
  if (request.method === "POST" && url.pathname === "/v1/claims/pull") {
    return pullResponse(request, env, resolvedStore);
  }
  const ackMatch = url.pathname.match(/^\/v1\/claims\/(RQ-[A-Z0-9]{16})\/ack$/);
  if (request.method === "POST" && ackMatch) {
    return ackResponse(request, env, resolvedStore, ackMatch[1]);
  }
  const failMatch = url.pathname.match(/^\/v1\/claims\/(RQ-[A-Z0-9]{16})\/fail$/);
  if (request.method === "POST" && failMatch) {
    return failResponse(request, env, resolvedStore, failMatch[1]);
  }
  const adminMatch = url.pathname.match(/^\/v1\/admin\/(RQ-[A-Z0-9]{16})$/);
  if (request.method === "DELETE" && adminMatch) {
    await authorize(request, env);
    const removed = await resolvedStore.remove(adminMatch[1]);
    return json({ ok: true, removed, receipt_id: adminMatch[1] });
  }
  throw new HttpError(404, "not_found", "接口不存在。");
}

export default {
  async fetch(request, env) {
    try {
      return await handleRequest(request, env);
    } catch (error) {
      const safe = error instanceof HttpError
        ? error
        : new HttpError(500, "internal_error", "提交服务暂时不可用，请稍后重试。");
      return json(
        { ok: false, error: safe.code, message: safe.message },
        { status: safe.status, origin: requestOrigin(request), env },
      );
    }
  },
};
