# Local EP Windows release tooling

These commands record the Windows build correction in Git. They do **not**
install Codex, change PATH, create tags, push to GitHub, or publish a Release.
There is no new CI workflow in this change. Keep the existing Linux entrypoint
`scripts/release-ep.sh`; do not apply Windows CRLF conversion to Linux builds.

## Why the isolated checkout matters

For the audited `rust-v0.162.1` baseline, the state source tree in EP is identical
to upstream. SQLx hashes the exact embedded migration bytes. The verified
official Windows binary uses CRLF checksums, whereas the earlier published EP.7
Windows binary was compiled from LF SQL. This is a build-input incompatibility,
not evidence of a corrupt database or a fork-specific schema change.

`scripts/ep_windows_release.py` explicitly sets `core.autocrlf=true` **only in a
new isolated checkout**, before checking out the selected commit. It checks the
whole state source tree against an explicit local upstream Git ref, then checks
every SQL file in all six migration families byte-for-byte against the CRLF
form of its Git blob (75 files at this baseline). It never edits migration SQL,
rewrites applied checksums, disables SQLx validation, or changes the original
repository's Git configuration. This makes the observed Windows artifact
behavior explicit; it is not a claim that upstream's workflow explicitly pins
this Git setting.

The published EP.7 Release has **not** been replaced. A corrected local EP.7
build still reports EP.7; it must not be relabeled as EP.8. A future release
requires its own version commit, rebuild, tests, and tag. Profiles initialized
by older LF Windows builds remain incompatible with the CRLF build; this tool
does not silently repair or convert them.

## Prerequisites

- Windows x64, Python 3.10+, Git, and Rustup with the toolchain and components
  pinned in `codex-rs/rust-toolchain.toml`.
- A configured MSVC/Windows SDK developer shell, CMake and Ninja as required
  by the native dependencies.
- The upstream pinned rusty-v8 archive and generated binding, with
  `RUSTY_V8_ARCHIVE` and `RUSTY_V8_SRC_BINDING_PATH` set in the shell. See
  `.github/actions/setup-rusty-v8` for the upstream download/hash protocol.
- For packaging: `zstd` or DotSlash on PATH. The upstream Python packager
  fetches/hash-verifies ripgrep from its pinned manifest, or accepts an explicit
  Windows `--rg-bin` for a prepared/offline helper.
- A clean, committed source tree and the official baseline ref locally
  available. The default baseline is `rust-v0.162.1`; review and explicitly
  update it when merging a different upstream release.

No personal cache paths, credentials, database backups, or compiled binaries
belong in Git. `.build-tools/` and `dist/` stay ignored. The script does not
download a compiler or configure MSVC/V8 for you. `--offline` additionally
requires all Cargo dependencies already cached.

## Build

Run from the repository root in the prepared developer PowerShell:

```powershell
# Use a new directory each time; existing outputs are never cleared/replaced.
python scripts/ep_windows_release.py build --work-dir D:\Builds\ep-windows-001

# Optional: prepare/check a new checkout without compiling anything.
python scripts/ep_windows_release.py build --work-dir D:\Builds\ep-preflight-001 --prepare-only
```

Options include `--ref HEAD`, `--jobs 3`, `--offline`, and
`--cargo-build-dir D:\BuildCaches\ep-intermediates`. Cargo's registry/git caches
remain controlled by the caller's `CARGO_HOME`. The isolated clone borrows Git
objects from the source repository (`git clone --shared`); retain that repository
while using the build checkout. The helper uses the upstream Windows binary
list and pinned Rust toolchain, leaving MSVC/V8 setup in the caller's environment.
It writes `build-state.json`, `migration-inputs.json`, `cargo-build.log`, and
fresh `target/` executables without touching installed Codex.

To inspect an existing clean Windows checkout without compiling:

```powershell
python scripts/ep_windows_release.py check-inputs --repo D:\Builds\ep-windows-001\source
```

An LF checkout fails this Windows-only check even if `git status` is clean.
This is intentional; it is not an instruction to change your editing checkout.

## Verify

```powershell
python scripts/ep_windows_release.py verify `
  --build-state D:\Builds\ep-windows-001\build-state.json `
  --output-dir D:\Builds\ep-verification-001 `
  --reference-exe D:\ReferenceBinaries\official-codex-0.162.1.exe
```

Supply an independently verified **official Windows binary for the same base
version**. The script checks its reported version and records its SHA-256; it
does not download or authenticate the reference binary on your behalf.
`--reference-exe` is optional for a fresh-database smoke check, but a fresh-only
result is **not** the cross-compatibility acceptance required for a release.

Verification checks all compiled artifact hashes and AMD64 PE headers, version,
help, PowerShell completion, fresh database integrity, and embedded migration
checksums. It creates only new isolated test profiles under the requested new
output directory, overrides both `CODEX_HOME` and `CODEX_SQLITE_HOME`, removes
API-key environment variables, disables update checks/apps/plugins/daemon
auto-start, and sends only the app-server initialize request, not model requests.
With the reference binary, it tests both new-build-open-reference and
reference-open-new using copies of these newly generated fixtures, preserving
all six migration metadata fields. It never reads an existing user profile.

Optionally pass `--legacy-exe D:\ReferenceBinaries\old-lf-ep7.exe` to generate
a separate legacy fixture and verify that its incompatible checksum is still
rejected without rewriting migration metadata. The lazy thread-history family
is covered by the source-byte guard; ordinary fresh app-server startup does not
initialize that database. Results go to `verification.json`; failed checks are
recorded as failed, not reported as successful.

## Package

```powershell
python scripts/ep_windows_release.py package `
  --build-state D:\Builds\ep-windows-001\build-state.json `
  --verification D:\Builds\ep-verification-001\verification.json `
  --output-dir D:\Builds\ep-package-001
```

This reuses the unchanged upstream `scripts/build_codex_package.py` directly,
so no WSL or Bash is needed on Windows. It supplies all prebuilt package helpers
explicitly; the packager must not rebuild them from an unchecked checkout.
The output has a portable `package/` directory plus `.tar.gz` and `.tar.zst`,
`codex-package_SHA256SUMS` covering **both** archives, both installers,
`SOURCE_COMMIT.txt`, and `BUILD_INFO.json`. It checks safe archive paths, helper
presence, source/build/verification/version identity, executable hashes, and
identical uncompressed gzip/zstd content. There is no Azure signing or optional
voice-runtime preparation. Packaging is not publication or installation.
Installer assets use their committed Git blob bytes, not the converted Windows
working-tree files, so the Linux bootstrap retains its canonical LF endings.

## Offline regression tests

```powershell
python -m unittest discover -s scripts -p test_ep_windows_release.py -v
```

The upstream packager tests also exercise Unix executable permission bits, so
run that complete suite from a Linux/WSL shell at the repository root:

```sh
CODEX_REPO_ROOT="$PWD" python3 -m unittest discover -s scripts/codex_package -p 'test_*.py' -v
```

The EP regression tests use temporary local Git repositories, dummy executable
headers and synthetic archives. They do not compile Rust, contact GitHub, run
model inference, or open the real Codex databases.
