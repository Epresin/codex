# GitHub edge proxy

A small Cloudflare Worker for Git HTTPS, repository REST API, and downloads.
Only the owners in `src/index.ts` are allowed (currently `epresin`). There is
no webpage/login proxy, server-side GitHub token, R2 bucket, or database.

## Routes

| Proxy path | Upstream |
| --- | --- |
| `/Epresin/REPO.git/...` | GitHub smart HTTP (`info/refs`, upload-pack, receive-pack) |
| `/api/repos/Epresin/...` | GitHub repository REST API |
| `/api/users/Epresin/...` | GitHub public user API |
| `/Epresin/REPO/releases/download/TAG/FILE` | Release download (redirects followed server-side) |
| `/raw/Epresin/REPO/REF/PATH` | Raw files |
| `/codeload/Epresin/REPO/...` | Source archives |

If GitHub throttles the shared Cloudflare anonymous API egress, public release
`latest`/`tags/...` queries fall back to the public release page and return the
minimal installer fields (`tag_name`, asset names, download URLs). Other API
queries keep their upstream status and response. Authenticated API requests
always use the real REST API.

GitHub credentials are forwarded, not replaced by a shared token. Configure
Git credentials for the proxy hostname when using authenticated Git; a cached
credential for `github.com` is not automatically a credential for another host.
Only HTTPS Git is handled, not SSH or Git LFS.

Git traffic, writes, authenticated responses, and range requests are not cached.
Public full downloads use the edge Cache API (one day for versioned release
files/source archives, one minute for API/raw files). `X-GitHub-Cache` reports
`HIT`, `MISS`, or `BYPASS`. The cache is opportunistic and local to each edge
location, not a permanent file store. Files are streamed, not buffered in memory.
Upstream private/no-store responses are not cached.

Cloudflare's current Free-zone request-body limit is 100 MB, including a Git
push's pack data. Download responses do not have that upload limit. This service
cannot lift it. A strict Epresin allowlist also excludes an `openai/codex`
upstream remote; add another owner explicitly if that is wanted later.

## Deploy

Use the already-authenticated Cloudflare CLI. No account token belongs in this
repository. Set `CLOUDFLARE_ACCOUNT_ID` if the CLI needs an account selection.

```sh
npm ci
npm run build
cf deploy --prebuilt
```

The hostname is configured in `cloudflare.config.ts`. Change it before deploying
a separate copy. This project uses the standard `cf init`/Vite tooling and does
not build the Codex Rust workspace.
