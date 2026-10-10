# API-key and custom-base-URL compatibility

This is an independent fork of the official OpenAI Codex CLI, based on
`rust-v0.162.1` (`092d3acd6bec3e3a14bdc7e7a2810ab628ab759d`).
The current EP release version is `0.162.1-ep.2`.
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
5. Identify fork builds with an `-ep.N` version suffix. All update entrypoints
   use this repository's Release API and the upstream standalone installer.
   Package-manager update actions and OpenAI CDN/npm-archive fallback paths
   are removed; model inference configuration is unrelated to updates.

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
curl -fsSL https://gh.mccts.cn/raw/Epresin/codex/ep/scripts/install/install.sh | CODEX_NON_INTERACTIVE=1 sh
```

The installer prefers `gh.mccts.cn` for release metadata and downloads and
falls back to GitHub if an accelerated request fails. `CODEX_RELEASES_API_URL`
still overrides the metadata source. The proxy uses a Worker and edge cache,
not R2; see `scripts/github-proxy/README.md`. No Rust rebuild is needed for
this installer change. The EP.2 binary bootstrap limitation below still applies.

This uses the upstream standalone directory layout under
`$CODEX_HOME/packages/standalone` (normally `~/.codex/packages/standalone`)
and places the visible command in `~/.local/bin`. It preserves existing
Codex configuration, API-key authentication, and old version directories.
Run `codex update` for subsequent upgrades; startup update prompts use the
same installer. Set `check_for_update_on_startup = false` to disable prompts.
Only targets with uploaded release assets can be installed. This release
provides Linux x86_64 musl; the Windows installer shares the same protocol,
but no Windows build is published by this release.

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
The `ep` branch's Rust update constants now point directly to GitHub; these
constant changes will take effect in the next compiled release, not in the
reused EP.2 binaries. No binary patching or version relabeling is performed.

## Version identity and update checks

`codex --version` and the TUI header report `0.162.1-ep.2`.
New releases use the tag form `rust-v0.162.1-ep.2`; earlier
`api-key-compat-v...` tags remain unchanged.

The startup prompt, `codex update`, update diagnostics, and the background
server's installer URL point to EP, never the official distribution. The EP.2
binary's legacy Gitee bootstrap is described in the migration note above.
The existing 20-hour cache and confirmation UI are retained. The cache is
`$CODEX_HOME/ep-version.json`, separate from old official version metadata.
Checks are enabled by default; explicit user configuration takes precedence.
Semantic-version comparison recognizes numeric `-ep.N` revisions.
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
