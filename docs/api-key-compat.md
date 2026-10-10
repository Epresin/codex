# API-key and custom-base-URL compatibility

This is an independent fork of the official OpenAI Codex CLI, based on
`rust-v0.162.0` (`c1382380de69521303b416720a52f42d51af6248`).
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

Each functional patch includes its focused regression tests. Search, image
handling, compaction, and HTTP streaming reuse the upstream implementations.
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
workspace package versions in `codex-rs/Cargo.lock` with the 0.162.0 manifests.
It does not upgrade external dependencies. Recheck whether a newer upstream
release needs this correction; do not carry it forward automatically.

## Verification

### Initial compatibility-patch verification

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

## Maintaining the fork

- `upstream` points to the official `openai/codex` Git repository.
- `origin` points to this personal fork on Gitee.
- `main` contains the selected upstream release plus the small patch series.
- The gateway project is maintained in a separate repository and release line.

For an upgrade, fetch the selected official release tag and create an upgrade
branch. Replay the two compatibility patches and the HTTP/SSE-default patch,
along with their documentation changes, reviewing any upstream refactoring.
Apply the lockfile correction only if it is still needed. If upstream implements the desired behavior, drop the
corresponding local patch rather than maintaining a duplicate implementation.
Build and rerun the focused tests and compatibility acceptance before
promoting the new version. Keep the previously verified tag available.
