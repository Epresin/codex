// Git HTTPS and public downloads only; no GitHub browser-session proxy.
const owners = new Set(["epresin"]);
const origins = {
  api: "https://api.github.com",
  raw: "https://raw.githubusercontent.com",
  codeload: "https://codeload.github.com",
};

function allowed(url: URL) {
  const parts = url.pathname.split("/").filter(Boolean);
  if (url.protocol !== "https:") return false;
  if (url.hostname === "api.github.com") {
    return ["repos", "users"].includes(parts[0]) && owners.has(parts[1]?.toLowerCase());
  }
  if (!owners.has(parts[0]?.toLowerCase())) return false;
  if (url.hostname === "raw.githubusercontent.com" || url.hostname === "codeload.github.com") return true;
  return url.hostname === "github.com" && /^\/[^/]+\/[^/]+\/(info\/refs|git-upload-pack|git-receive-pack|releases\/(download|latest\/download)\/.*|archive\/.*)$/.test(url.pathname);
}

function proxyUrl(value: string, origin: string) {
  if (!value.startsWith("https://")) return value;
  try {
    const url = new URL(value);
    if (!allowed(url)) return value;
    const prefix = Object.entries(origins).find(([, host]) => host === url.origin)?.[0];
    return origin + (prefix ? "/" + prefix : "") + url.pathname + url.search;
  } catch {
    return value;
  }
}

// Cloudflare shared egress can exhaust GitHub's anonymous REST quota.
// The installer only needs the public tag and asset links; no stored PAT needed.
async function publicRelease(target: URL) {
  const match = target.pathname.match(/^\/repos\/([^/]+)\/([^/]+)\/releases\/(latest|tags\/(.+))$/);
  if (!match) return null;
  const [, owner, repo, , requestedTag] = match;
  const github = `https://github.com/${owner}/${repo}`;
  let tag = requestedTag;
  if (!tag) {
    const latest = await fetch(github + "/releases/latest", { redirect: "manual" });
    const location = latest.headers.get("Location");
    await latest.body?.cancel();
    if (!location) return null;
    tag = new URL(location, github).pathname.split("/releases/tag/")[1];
  }
  if (!tag) return null;
  const html = await fetch(github + "/releases/expanded_assets/" + tag);
  if (!html.ok) { await html.body?.cancel(); return null; }
  const assets: { name: string; browser_download_url: string }[] = [];
  await new HTMLRewriter().on("a[href]", {
    element(element) {
      const url = new URL(element.getAttribute("href")!, github);
      if (url.pathname.toLowerCase().startsWith(`/${owner}/${repo}/releases/download/`.toLowerCase())) {
        assets.push({ name: decodeURIComponent(url.pathname.split("/").at(-1)!), browser_download_url: url.href });
      }
    },
  }).transform(html).text();
  return Response.json({ tag_name: decodeURIComponent(tag), assets }, { headers: { "Cache-Control": "public, max-age=60", "X-GitHub-Metadata": "public-release-fallback" } });
}

export default {
  async fetch(request: Request, _env: unknown, ctx: ExecutionContext) {
    const incoming = new URL(request.url);
    const prefix = incoming.pathname.split("/")[1] as keyof typeof origins;
    const base = origins[prefix];
    const target = new URL((base ? incoming.pathname.slice(prefix.length + 1) : incoming.pathname) + incoming.search, base || "https://github.com");
    if (!allowed(target)) return new Response("Only Epresin Git HTTPS, repository API and download paths are supported.\n", { status: 404 });

    const isGit = target.hostname === "github.com" && /\/(info\/refs|git-upload-pack|git-receive-pack)$/.test(target.pathname);
    const authenticated = request.headers.has("Authorization") || request.headers.has("Cookie") || target.searchParams.has("token");
    const cacheable = request.method === "GET" && !isGit && !authenticated && !request.headers.has("Range");
    const cacheKey = new Request(incoming.toString());
    if (cacheable) {
      const hit = await caches.default.match(cacheKey);
      if (hit) {
        const response = new Response(hit.body, hit);
        response.headers.set("X-GitHub-Cache", "HIT");
        return response;
      }
    }

    const headers = new Headers(request.headers);
    headers.delete("Cookie");
    headers.delete("Host");
    headers.set("User-Agent", "epresin-github-edge");
    let upstream = await fetch(new Request(target, {
      method: request.method,
      headers,
      body: ["GET", "HEAD"].includes(request.method) ? undefined : request.body,
      redirect: "manual",
    }));

    if (!authenticated && request.method === "GET" && target.hostname === "api.github.com" && upstream.status === 403 && upstream.headers.get("X-RateLimit-Remaining") === "0") {
      const fallback = await publicRelease(target);
      if (fallback) { await upstream.body?.cancel(); upstream = fallback; }
    }

    // Follow download redirects inside the Worker, not on the user's network.
    // Git/API writes keep their original response; never replay a streamed POST.
    let next = target;
    if (["GET", "HEAD"].includes(request.method) && !isGit) {
      for (let i = 0; i < 5 && [301, 302, 303, 307, 308].includes(upstream.status); i++) {
        const location = upstream.headers.get("Location");
        if (!location) break;
        const redirect = new URL(location, next);
        if (redirect.origin !== next.origin) headers.delete("Authorization");
        await upstream.body?.cancel();
        next = redirect;
        upstream = await fetch(next, { method: request.method, headers, redirect: "manual" });
      }
    }

    let response = new Response(upstream.body, upstream);
    // Keep API-provided download URLs on this service as well.
    if (target.hostname === "api.github.com" && request.method !== "HEAD" && upstream.headers.get("Content-Type")?.includes("application/json")) {
      const body = JSON.stringify(await upstream.json(), (_key, value) => typeof value === "string" ? proxyUrl(value, incoming.origin) : value);
      response = new Response(body, { status: upstream.status, headers: upstream.headers });
      response.headers.delete("Content-Length");
      response.headers.delete("Content-Encoding");
      response.headers.delete("ETag");
    }
    const location = response.headers.get("Location");
    if (location) response.headers.set("Location", proxyUrl(new URL(location, target).href, incoming.origin));
    const link = response.headers.get("Link");
    if (link) response.headers.set("Link", link.replace(/<([^>]+)>/g, (_match, url) => "<" + proxyUrl(url, incoming.origin) + ">"));
    response.headers.delete("Set-Cookie");
    response.headers.set("X-GitHub-Cache", cacheable ? "MISS" : "BYPASS");

    const privateResponse = /private|no-store/i.test(upstream.headers.get("Cache-Control") || "");
    if (cacheable && upstream.status === 200 && !privateResponse) {
      const file = target.hostname === "github.com" && /\/releases\/download\//.test(target.pathname);
      response.headers.set("Cache-Control", "public, max-age=" + (file ? 86400 : 60));
      ctx.waitUntil(caches.default.put(cacheKey, response.clone()).catch(() => {}));
    } else {
      response.headers.set("Cache-Control", "no-store");
    }
    return response;
  },
};
