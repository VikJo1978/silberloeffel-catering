/**
 * External Secure Intake Layer — Cloudflare Worker (Slice A pack §8,
 * INTEGRATION_DEPLOYMENT_EXECUTION_PACK_V1 §1).
 *
 * Role: terminate public Wix-form traffic, validate/sanitize/minimally
 * normalize, forward to the configured upstream with a server-side secret.
 * The browser never sees UPSTREAM_TOKEN. This worker holds no business logic
 * and is not operational truth (§8.3).
 *
 * Env bindings (wrangler.toml / dashboard):
 *   UPSTREAM_URL   — office-facing intake endpoint to forward to
 *   UPSTREAM_TOKEN — bearer secret for the upstream (server-side only)
 */

const MAX_BODY_BYTES = 16 * 1024;

const ALLOWED_FIELDS = new Set([
  "event_date",
  "time_window_text",
  "location_text",
  "guest_count_estimate",
  "planning_mode",
  "customer_linkage",
]);

const TEXT_FIELDS = ["time_window_text", "location_text"];

function sanitize(raw) {
  const out = {};
  for (const [key, value] of Object.entries(raw)) {
    if (!ALLOWED_FIELDS.has(key)) continue; // strip everything not whitelisted
    out[key] = value;
  }
  for (const key of TEXT_FIELDS) {
    if (typeof out[key] === "string") out[key] = out[key].trim().slice(0, 500);
  }
  if (typeof out.event_date !== "string" || !/^\d{4}-\d{2}-\d{2}$/.test(out.event_date)) {
    return null; // event_date is required and must be ISO yyyy-mm-dd
  }
  // Minimal normalization (§8.2): Wix form fields often arrive as strings —
  // coerce digit-only strings to integers; reject anything else non-integer.
  if (typeof out.guest_count_estimate === "string" && /^\d+$/.test(out.guest_count_estimate)) {
    out.guest_count_estimate = Number(out.guest_count_estimate);
  }
  if (out.guest_count_estimate !== undefined && !Number.isInteger(out.guest_count_estimate)) {
    return null;
  }
  return out;
}

export default {
  async fetch(request, env) {
    if (request.method !== "POST") {
      return new Response("method not allowed", { status: 405 });
    }
    const length = Number(request.headers.get("content-length") || "0");
    if (length > MAX_BODY_BYTES) {
      return new Response("payload too large", { status: 413 });
    }
    let raw;
    try {
      raw = await request.json();
    } catch {
      return new Response("invalid json", { status: 400 });
    }
    const clean = sanitize(raw);
    if (clean === null) {
      return new Response("invalid inquiry payload", { status: 422 });
    }
    const upstream = await fetch(env.UPSTREAM_URL, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        Authorization: `Bearer ${env.UPSTREAM_TOKEN}`,
      },
      body: JSON.stringify(clean),
    });
    // Never relay upstream body or headers to the public caller.
    return new Response(upstream.ok ? "accepted" : "upstream error", {
      status: upstream.ok ? 202 : 502,
    });
  },
};
