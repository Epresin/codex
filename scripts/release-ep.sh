#!/usr/bin/env bash
# Build standard EP release archives from prebuilt binaries using upstream tooling.
set -euo pipefail
if [[ $# -lt 3 ]]; then
  echo "Usage: release-ep.sh TARGET BINARY_DIR OUTPUT_DIR [upstream packaging options...]" >&2
  exit 1
fi
target="$1"
binaries="$(cd "$2" && pwd)"
mkdir -p "$3"
out="$(cd "$3" && pwd)"
shift 3
root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
export CODEX_REPO_ROOT="$root"
export RUNNER_TEMP
RUNNER_TEMP="$(mktemp -d)"
trap 'rm -rf "$RUNNER_TEMP"' EXIT
bash "$root/.github/scripts/build-codex-package-archive.sh" \
  --target "$target" --bundle primary --entrypoint-dir "$binaries" \
  --archive-dir "$out" "$@"
(cd "$out" && sha256sum codex-package-*.tar.gz > codex-package_SHA256SUMS)
cp "$root/scripts/install/install.sh" "$root/scripts/install/install.ps1" "$out/"
git -C "$root" rev-parse HEAD > "$out/SOURCE_COMMIT.txt"
printf 'Release artifacts: %s\n' "$out"
