# API-key and custom-base-URL compatibility

This is an independent fork of the official OpenAI Codex CLI, based on
`rust-v0.163.0` (`83086188ae0614bd882818ff1aa23f3194962012`).
The current EPR release version is `0.163.0-epr.1`.
It is not a client for a specific gateway. No gateway server, deployment
configuration, credentials, or private acceptance sessions are included.
The upstream Apache-2.0 license and NOTICE are preserved.

## Changes

1. When the native `openai` provider has an explicit base URL, derive its
   rich model-catalog URL as `<base_url>/models`.
2. Allow the existing native image-generation implementation for API-key
   authentication with an explicit base URL, while retaining the existing
   feature, model-capability, tool-policy, and sandbox checks.
3. Use HTTP/SSE instead of WebSocket transport for the native `openai` provider's
   Responses requests. With an HTTPS base URL, inference starts over HTTPS
   without WebSocket preconnection or failed WebSocket retries first.

4. On WSL, treat empty terminal paste events as image-paste requests. Read the
   Windows clipboard through PowerShell as base64 PNG bytes and save the image
   locally in WSL, without mapping Windows temporary-file paths. Existing image
   shortcuts and ordinary text paste are preserved.
5. Identify fork builds with an `-epr.N` version suffix (legacy `-ep.N` remains supported). The revision restarts at 1 when the upstream base changes. All update entrypoints
   use this repository's Release API and the upstream standalone installer.
   Package-manager update actions and OpenAI CDN/npm-archive fallback paths
   are removed; model inference configuration is unrelated to updates.
6. New builds from the EP branch enable MultiAgentV2 by default. Users can
   explicitly select V1 through configuration; see the EP.4 change below.

Search, image handling, compaction, and HTTP streaming reuse the upstream
implementations. The WSL patch only changes local clipboard input.
The transport default does not change authentication or the model catalog,
and does not alter app-server, MCP, or realtime connections. The client remains
in API-key mode; it does not impersonate ChatGPT authentication or a subscription
plan.

The endpoint must implement the relevant protocol. In particular, dynamic
Codex metadata requires the Codex rich `/models` response, not just an ordinary
OpenAI-compatible list of model IDs. Availability of native image, search,
and compaction operations depends on the endpoint and selected model.
There is no dependency on New API, CLIProxyAPI, a particular hostname, or
any locally installed gateway.

## Configuration

Use the normal Codex config and API-key authentication mechanism:

```toml
model_provider = "openai"
openai_base_url = "https://your-compatible-api.example/v1"
model = "YOUR_MODEL_ID"
```

Authenticate with the API key issued by that endpoint, using the upstream
API-key sign-in flow. A ChatGPT login and a custom key header are not required
for these patches. See the upstream documentation for normal CLI setup,
credentials storage, and build instructions.

## Upstream 0.163.0 and EPR naming (0.163.0-epr.1)

- Merge the official `rust-v0.163.0` release while retaining the compact
  `64k/1m` context footer and existing API-key/HTTP/WSL compatibility changes.
- Use `-epr.N` for new releases; both installers continue accepting old `-ep.N` versions.
- Preserve the official background compaction implementation and its default-off
  `async_compaction` feature. Publishing this release does not enable it in user profiles.
- Build Windows from an isolated CRLF checkout and Linux from LF source.
  The state tree is identical to upstream; no migration or applied-checksum rewriting
  is performed. Windows release acceptance includes cross-opening fresh test
  databases with the official Windows binary for the same base version.
- Older LF-built EP Windows databases are not silently converted. Back up
  profiles before upgrading; the earlier checksum mismatch was a build-input
  incompatibility, not proof of database corruption.

## Compact context status line (0.162.1-ep.7)

The `context-window` footer item now shows only current context tokens / capacity,
such as `64k/1m` or `64k/256k`, with lowercase units and no label, percentage, or
spaces. The status-line picker preview uses the same compact format.

The token counts match `/status`; only this footer item's formatting is
simplified. It still uses the last request's usage, not cumulative session
consumption, so compaction reduces the displayed occupancy. Runtime context
capacity takes precedence over configured capacity. Unknown or still-loading
context usage is omitted. Default selection and explicit user customization are
unchanged, and the `/status` card and other token display items are not modified.

## Context status line and Windows packages (0.162.1-ep.6)

EP.6 added `context-window` to the default TUI footer, showing the same remaining
percentage and current context tokens / capacity as `/status`. EP.7 simplifies
its display as described above, while preserving the underlying usage tracking.

Use `/statusline` to toggle or reorder this item. Existing explicit
`tui.status_line` configurations are preserved; add `context-window` there to
opt in. The separate `used-tokens` item still reports cumulative session usage.

This release adds a Windows x86_64 MSVC standalone package alongside the Linux
x86_64 musl package. Both contain freshly built EP.6 binaries and required
platform helpers. Windows binaries are not Authenticode-signed; optional voice
runtime resources are not included on either platform.

It also includes installer release-version validation, authenticated checksum
manifest verification when a digest is supplied, and recovery from interrupted,
corrupt, or non-resumable downloads. Existing configuration and authentication
are preserved.

## Ultra defaults (0.162.1-ep.5)

Confirming Ultra in `/model` now saves `model_reasoning_effort = "ultra"`
as the default for new conversations. EP no longer replaces the saved effort
with the previous non-Ultra setting while applying Ultra only to the active
conversation. The picker labels ordinary confirmation as `default`.

The explicit `s` / session-only action still changes only the active conversation
and preserves saved defaults. Existing higher-priority configuration and separate
saved Plan-mode defaults retain their precedence. Ultra's active-conversation
behavior, concurrency warning, and V2 proactive-delegation instructions are
otherwise unchanged.

## Subagent backend (0.162.1-ep.4)

EP.4 defaults to MultiAgentV2. Earlier release binaries and an installed Desktop
are unchanged until their Codex backend is updated to this build.

V2's `spawn_agent` guidance asks the parent to consult the available model
descriptions and explicitly select a model for the delegated task, respecting
the user's model requirements instead of merely inheriting the parent model.
Model roles and preferences remain description text supplied by the catalog;
EP does not parse role markers or hardcode model IDs. Explicit model or reasoning
selection is guided to use `fork_turns = "none"` with the needed task context.
The V1 model-selection guidance is unchanged.

To use the V1 subagent tools instead, add these settings to `config.toml`:

```toml
[features]
multi_agent = true
multi_agent_v2 = false
```

If `[features]` already exists, merge these keys into it rather than adding a
second table. The structured form `[features.multi_agent_v2]` with
`enabled = false` also works; do not combine it with the boolean form.
With `multi_agent` enabled, disabling V2 explicitly selects V1 even when the
model catalog or saved session metadata requests V2. Removing the V2 override,
or setting it to `true`, restores the EP default. This selection also applies
when resuming a session; it is not limited to newly created chats.

To disable subagents entirely, use `[agents]` with `enabled = false`. That
master switch takes precedence over the default or explicitly enabled V2.

Restart the CLI or the Desktop app-server that runs this EP build after changing
these settings. No Desktop frontend patch is needed to change this backend
selection, but Desktop must actually be using the EP binary.

## Build note

This baseline pins Rust 1.95.0. A separate build-only commit aligns the local
workspace package versions in `codex-rs/Cargo.lock` with the release manifests
(including the EP suffix).
It does not upgrade external dependencies. Recheck whether a newer upstream
release needs this correction; do not carry it forward automatically.

## Verification

### Initial 0.162.0 compatibility-patch verification

The functional patches were compiled with Rust 1.95.0 on Windows using the
`dev-small` profile. The 37 focused tests passed: 34 provider-info tests,
two model-provider tests, and one native image-generation gate test.
The entire upstream test suite and an optimized release build were not run.

An isolated API-key-only acceptance run against a compatible endpoint passed
dynamic catalog discovery, native search, image generation and editing,
manual and automatic compaction with recall, and WebSocket transport.
These are compatibility observations, not a claim that every endpoint or
model supports all of those operations. Private test data and deployment
logs are intentionally kept outside this fork.

### HTTP/SSE-default verification

The provider-info crate's 35 unit tests passed on Windows with:

```shell
cargo test --offline --locked --profile dev-small -p codex-model-provider-info --lib
```

The new regression test checks the built-in `openai` provider both with and
without an explicit base URL. HTTP/SSE is selected while the provider identity,
Responses wire API, authentication requirement, and standalone search capability
remain unchanged. No new end-to-end gateway or corporate-proxy acceptance was
run for this transport-default change.

## Install and update

The repository and its release assets are public. Install the Linux package
with the fork's standalone installer (no GitHub token is required):

```sh
if s=$(curl -fsSL --connect-timeout 5 --max-time 8 https://raw.githubusercontent.com/Epresin/codex/ep/scripts/install/install.sh) ||
   s=$(curl -fsSL --connect-timeout 1800 --max-time 1800 https://gh.mccts.cn/raw/Epresin/codex/ep/scripts/install/install.sh); then
  printf '%s\n' "$s" | CODEX_NON_INTERACTIVE=1 sh
fi
```

EP.3 prefers GitHub for update checks, installer bootstrap, and package files.
The EP.3 binary's metadata and bootstrap requests have an eight-second total
deadline (the doctor and daemon use the same deadline). The online installer
keeps GitHub's five-second connection/eight-second metadata timeouts and falls
back after ten seconds below 256 KiB/s for packages. Its Cloudflare requests now
allow 1,800 seconds to connect. Cloudflare file downloads have no total-time
limit: they stop only after 1,800 seconds below 1 byte/second. Metadata retains
its 1,800-second total deadline. File transfers show progress; metadata stays
silent. Interrupted archives are retained under
`$CODEX_HOME/packages/standalone/downloads/<sha256>.part` (or the daemon package
root). GitHub-to-Cloudflare fallback and rerunning the installer resume the same
file. SHA-256 is checked before installation; successful installation removes
the cached archive.
The wget compatibility path uses connection/stalled-read timeouts (also 1,800
seconds for Cloudflare) instead of curl's total-time/minimum-speed controls.
This script-only update does not change the EP.3 binary's compiled bootstrap
timeout; use the command above when a longer initial Cloudflare wait is needed.
The Windows standalone installer/bootstrap use the built-in `curl.exe`.

`CODEX_RELEASES_API_URL` still overrides the metadata source. Even when metadata
came from Cloudflare, package links are normalized to GitHub and attempted there
first. When release metadata supplies a SHA-256 digest, the installers verify the
checksum manifest against it before trusting its package hashes. Missing or null
digests remain supported for compatible release APIs; malformed supplied digests
are rejected. Download or verification failures try the fallback, discarding
corrupt bytes but retaining interrupted transfers for resume. If a server cannot
resume a partial file (including HTTP 416), the installer retries that source
once from the beginning. Explicit release requests must match the version in
the returned metadata. Checksums are verified after either path. Failed/partial bootstrap output
is discarded before the fallback script is executed. No new user config is
required. The proxy uses a Worker and edge cache, not R2; see
`scripts/github-proxy/README.md`.

This uses the upstream standalone directory layout under
`$CODEX_HOME/packages/standalone` (normally `~/.codex/packages/standalone`)
and places the visible command in `~/.local/bin`. It preserves existing
Codex configuration, API-key authentication, and old version directories.
Run `codex update` for subsequent upgrades; startup update prompts use the
same installer. Set `check_for_update_on_startup = false` to disable prompts.
Only targets with uploaded release assets can be installed. This release
provides Linux x86_64 musl and Windows x86_64 MSVC. The Windows installer
uses the same release and checksum protocol.

## GitHub migration (2026-10-10)

The GitHub `rust-v0.162.1-ep.2` release reuses the already-built Linux archives
from commit `34752d7aacef04ff35e4e5d1afc3503b6a3e2394` byte for byte.
The version, binaries, archive checksums, and original tag are unchanged;
this migration does not rerun the Rust build or the model acceptance tests.
Release installer scripts are updated separately to download from GitHub.
`BUILD_INFO.json` identifies the binary source commit and installer source commit.

The reused EP.2 binaries still contain Gitee URLs for update checks and the
installer bootstrap. The old Gitee installer endpoint is retained and now
queries GitHub Releases, so `codex update` can download this GitHub package.
The old Gitee EP.2 release is retained as a migration notice, not a binary host.
EP.3 replaces those compiled constants with GitHub-first/Cloudflare-fallback
entrypoints. This does not change the already-published EP.2 binaries. No binary patching or version relabeling is performed.

## Version identity and update checks

`codex --version` and the TUI header report `0.163.0-epr.1`.
This release uses `rust-v0.163.0-epr.1`; earlier
`api-key-compat-v...` tags remain unchanged.

The startup prompt, `codex update`, update diagnostics, and the background
server's installer URL point to EP, never the official distribution. The EP.2
binary's legacy Gitee bootstrap is described in the migration note above.
The existing 20-hour cache and confirmation UI are retained. The cache is
`$CODEX_HOME/ep-version.json`, separate from old official version metadata.
Checks are enabled by default; explicit user configuration takes precedence.
Semantic-version comparison recognizes numeric `-epr.N` and legacy `-ep.N` revisions.
Background-service management and local CLI-to-daemon synchronization are
preserved, rather than deleting functionality unrelated to release discovery.

The installers use the shared GitHub/Gitee Release fields `tag_name`,
`assets[].name`, and `assets[].browser_download_url`. They verify archives
using `codex-package_SHA256SUMS`, without requiring GitHub-only asset digests.
To use another compatible repository, the installer accepts
`CODEX_RELEASES_API_URL` (the `/repos/OWNER/REPO/releases` API base).
Rust entrypoint URLs are centralized in `codex-rs/install-context/src/release.rs`.
No account tokens or model gateway keys are embedded in the update path.

## Standard release packaging

For the isolated Windows CRLF build, migration-byte checks, executable/database
verification, and native Python packaging entrypoint, see
[Local EP Windows release tooling](ep-windows-build.md). These local tools do
not install or publish anything; GitHub CI is not introduced by that change.

After compiling the CLI, code-mode host, and platform helpers, call:

```sh
bash scripts/release-ep.sh x86_64-unknown-linux-musl /path/to/release/binaries /path/to/artifacts
```

This thin wrapper calls the unchanged upstream
`.github/scripts/build-codex-package-archive.sh`, which in turn uses
`scripts/build_codex_package.py`. Extra arguments are forwarded to the
upstream wrapper, for example `--rg-bin`, `--zsh-bin`, or prepared voice inputs.
It outputs `codex-package-TARGET.tar.gz`, `codex-package-TARGET.tar.zst`,
`codex-package_SHA256SUMS`, installer scripts, and the source commit.
Archive roots directly contain `bin/`, `codex-path/`, `codex-resources/`,
and `codex-package.json`; there is no extra enclosing version directory.
The base standard package includes the pinned ripgrep and zsh helpers.
Optional voice-runtime preparation remains the upstream release pipeline's
separate step; this fork does not add or maintain a second packaging engine.

## 0.162.1 upstream merge

The upstream update contains multiline async-question rendering fixes and a
fix that limits daemon feature compatibility checks to explicit CLI overrides.
Only the workspace version line conflicted during the merge; it was aligned
with 0.162.1 before the separate EP version commit. No functional patch conflicted.
External dependency versions were not upgraded by this fork.

## EP updater verification

For 0.162.1-ep.2, 20 focused TUI update/version tests passed and the four
changed update UI snapshots were refreshed. Two isolated shell-installer
checks passed: GitHub-style metadata with asset digests and Gitee-style
metadata without them, including EP versions and configuration preservation.
Both installer scripts passed syntax checks. These are targeted checks, not
a claim that the complete upstream test suite was run.

## Maintaining the fork

- `upstream` points to the official `openai/codex` Git repository.
- `origin` points to the public GitHub fork `Epresin/codex`, whose parent is
  `openai/codex`.
- `ep` is the default branch and contains the selected upstream release plus
  the small patch series. The GitHub `main` branch is kept as the upstream line.
- `gitee` retains the old repository for existing installation/update links.
- The gateway project is maintained in a separate repository and release line.

For an upgrade, fetch the selected official release tag and create an upgrade
branch. Merge the selected upstream release, or replay the small functional
commits onto it, reviewing any upstream refactoring. Keep transport, clipboard,
and EP version/update-policy changes in separate commits.
Apply the lockfile correction only if it is still needed. If upstream implements the desired behavior, drop the
corresponding local patch rather than maintaining a duplicate implementation.
Build and rerun the focused tests and compatibility acceptance before
promoting the new version. Keep the previously verified tag available.
