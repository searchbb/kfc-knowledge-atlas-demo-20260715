import assert from "node:assert/strict";
import test from "node:test";

import { proxyRequest } from "../functions/v1/[[path]].js";

const env = {
  UPSTREAM_WORKER_ORIGIN: "https://worker.account.workers.dev",
  PROXY_SHARED_SECRET: "proxy-secret-with-at-least-24-characters",
};

test("proxy forwards only safe headers and injects the private hop secret", async () => {
  const request = new Request("https://proxy.pages.dev/v1/submissions", {
    method: "POST",
    headers: {
      Origin: "https://searchbb.github.io",
      Authorization: "Bearer mac-token",
      "Content-Type": "application/json",
      Cookie: "must-not-forward",
      "CF-Connecting-IP": "203.0.113.42",
    },
    body: JSON.stringify({ title: "test" }),
  });
  let forwarded;
  const response = await proxyRequest(request, env, async (url, options) => {
    forwarded = { url, options };
    return new Response(JSON.stringify({ ok: true }), {
      status: 201,
      headers: { "Content-Type": "application/json", "Set-Cookie": "blocked=1" },
    });
  });
  assert.equal(response.status, 201);
  assert.equal(forwarded.url, "https://worker.account.workers.dev/v1/submissions");
  assert.equal(forwarded.options.headers.get("Origin"), "https://searchbb.github.io");
  assert.equal(forwarded.options.headers.get("Cookie"), null);
  assert.equal(forwarded.options.headers.get("X-Intake-Proxy-Secret"), env.PROXY_SHARED_SECRET);
  assert.equal(forwarded.options.headers.get("X-Intake-Client-IP"), "203.0.113.42");
  assert.equal(response.headers.get("Set-Cookie"), null);
});

test("invalid paths and missing configuration fail closed", async () => {
  const badPath = await proxyRequest(new Request("https://proxy.pages.dev/v1/../admin"), env);
  assert.equal(badPath.status, 404);
  const missingSecret = await proxyRequest(new Request("https://proxy.pages.dev/v1/challenge"), {
    UPSTREAM_WORKER_ORIGIN: env.UPSTREAM_WORKER_ORIGIN,
  });
  assert.equal(missingSecret.status, 503);
});

test("upstream network errors return a stable message without details", async () => {
  const response = await proxyRequest(
    new Request("https://proxy.pages.dev/v1/challenge"),
    env,
    async () => { throw new Error("sensitive network detail"); },
  );
  assert.equal(response.status, 502);
  const payload = await response.json();
  assert.equal(payload.error, "upstream_unavailable");
  assert.equal(JSON.stringify(payload).includes("sensitive"), false);
});
