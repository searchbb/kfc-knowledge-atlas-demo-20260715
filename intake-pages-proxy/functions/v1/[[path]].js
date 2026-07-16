const PATH_PATTERN = /^[a-zA-Z0-9/_-]{1,180}$/;
const FORWARDED_REQUEST_HEADERS = new Set(["origin", "authorization", "content-type"]);
const FORWARDED_RESPONSE_HEADERS = new Set([
  "access-control-allow-origin",
  "access-control-allow-headers",
  "access-control-allow-methods",
  "access-control-max-age",
  "cache-control",
  "content-type",
  "vary",
  "x-content-type-options",
]);

function json(status, payload) {
  return new Response(JSON.stringify(payload), {
    status,
    headers: {
      "Cache-Control": "no-store",
      "Content-Type": "application/json; charset=utf-8",
      "Referrer-Policy": "no-referrer",
      "X-Content-Type-Options": "nosniff",
    },
  });
}

function requestPath(request) {
  const pathname = new URL(request.url).pathname;
  if (!pathname.startsWith("/v1/")) return "";
  const path = pathname.slice(4);
  if (!PATH_PATTERN.test(path) || path.includes("..")) return "";
  return path;
}

export async function proxyRequest(request, env, fetchImpl = fetch) {
  const path = requestPath(request);
  const upstream = String(env.UPSTREAM_WORKER_ORIGIN || "").replace(/\/$/, "");
  const proxySecret = String(env.PROXY_SHARED_SECRET || "");
  if (!path) return json(404, { ok: false, error: "not_found", message: "接口不存在。" });
  if (!/^https:\/\/[a-z0-9.-]+\.workers\.dev$/i.test(upstream) || proxySecret.length < 24) {
    return json(503, { ok: false, error: "proxy_not_configured", message: "提交服务尚未完成配置。" });
  }

  const headers = new Headers();
  for (const [name, value] of request.headers.entries()) {
    if (FORWARDED_REQUEST_HEADERS.has(name.toLowerCase())) headers.set(name, value);
  }
  headers.set("X-Intake-Proxy-Secret", proxySecret);
  headers.set("X-Intake-Client-IP", request.headers.get("CF-Connecting-IP") || "unknown");

  let upstreamResponse;
  try {
    upstreamResponse = await fetchImpl(`${upstream}/v1/${path}`, {
      method: request.method,
      headers,
      body: ["GET", "HEAD", "OPTIONS"].includes(request.method) ? undefined : request.body,
      redirect: "manual",
    });
  } catch {
    return json(502, { ok: false, error: "upstream_unavailable", message: "提交服务暂时不可用，请稍后重试。" });
  }

  const responseHeaders = new Headers();
  for (const [name, value] of upstreamResponse.headers.entries()) {
    if (FORWARDED_RESPONSE_HEADERS.has(name.toLowerCase())) responseHeaders.set(name, value);
  }
  responseHeaders.set("Referrer-Policy", "no-referrer");
  responseHeaders.set("X-Content-Type-Options", "nosniff");
  return new Response(upstreamResponse.body, { status: upstreamResponse.status, headers: responseHeaders });
}

export function onRequest(context) {
  return proxyRequest(context.request, context.env);
}
