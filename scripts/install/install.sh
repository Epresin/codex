#!/bin/sh

set -eu

RELEASE="${CODEX_RELEASE:-latest}"
NON_INTERACTIVE="${CODEX_NON_INTERACTIVE:-false}"
DAEMON_ONLY="${CODEX_INSTALL_DAEMON_ONLY:-0}"
RELEASES_API_URL="${CODEX_RELEASES_API_URL:-https://api.github.com/repos/Epresin/codex/releases}"

BIN_DIR="${CODEX_INSTALL_DIR:-$HOME/.local/bin}"
BIN_PATH="$BIN_DIR/codex"
CODE_MODE_HOST_BIN_PATH="$BIN_DIR/codex-code-mode-host"
CODEX_HOME_DIR="${CODEX_HOME:-$HOME/.codex}"
STANDALONE_ROOT="$CODEX_HOME_DIR/packages/standalone"
if [ "$DAEMON_ONLY" = "1" ]; then
  STANDALONE_ROOT="$CODEX_HOME_DIR/packages/app-server-daemon"
fi
RELEASES_DIR="$STANDALONE_ROOT/releases"
CURRENT_LINK="$STANDALONE_ROOT/current"
if [ "${CODEX_INSTALL_DEFER_SELECTION:-0}" = "1" ]; then
  if [ "$DAEMON_ONLY" != "1" ]; then
    echo "Deferred selection requires a daemon-only installation." >&2
    exit 1
  fi
  CURRENT_LINK="$STANDALONE_ROOT/.migration-current"
fi
AUTO_UPDATE_VERSION="$STANDALONE_ROOT/auto-update-version"
LOCK_FILE="$STANDALONE_ROOT/install.lock"
LOCK_DIR="$STANDALONE_ROOT/install.lock.d"
LOCK_STALE_AFTER_SECS=600

path_action="already"
path_profile=""
conflict_manager=""
conflict_path=""
lock_kind=""
tmp_dir=""

step() {
  printf '==> %s\n' "$1"
}

warn() {
  printf 'WARNING: %s\n' "$1" >&2
}

normalize_version() {
  case "$1" in
    "" | latest)
      printf 'latest\n'
      ;;
    rust-v*)
      printf '%s\n' "${1#rust-v}"
      ;;
    v*)
      printf '%s\n' "${1#v}"
      ;;
    *)
      printf '%s\n' "$1"
      ;;
  esac
}

validate_version() {
  version="$1"

  if [ "$version" = "latest" ]; then
    return
  fi

  if ! printf '%s\n' "$version" | grep -Eq '^[0-9]+\.[0-9]+\.[0-9]+(-alpha(\.[0-9]+){0,2}|-beta(\.[0-9]+)?|-ep(\.[0-9]+)?)?$'; then
    echo "Invalid Codex release version: $version. Expected latest or x.y.z[-alpha[.N[.M]]|-beta[.N]|-ep[.N]]." >&2
    return 1
  fi
}

parse_args() {
  while [ "$#" -gt 0 ]; do
    case "$1" in
      --release)
        if [ "$#" -lt 2 ]; then
          echo "--release requires a value." >&2
          exit 1
        fi
        RELEASE="$2"
        shift
        ;;
      --help | -h)
        cat <<EOF
Usage: install.sh [--release VERSION]

Environment:
  CODEX_RELEASE          Version to install; overridden by --release.
  CODEX_NON_INTERACTIVE  Set to 1, true, or yes to skip prompts.
  CODEX_RELEASES_API_URL Release API base URL (GitHub/Gitee compatible).
EOF
        exit 0
        ;;
      *)
        echo "Unknown argument: $1" >&2
        exit 1
        ;;
    esac
    shift
  done
}

github_url() {
  case "$1" in
    https://gh.mccts.cn/api/*) printf 'https://api.github.com/%s\n' "${1#https://gh.mccts.cn/api/}" ;;
    https://gh.mccts.cn/raw/*) printf 'https://raw.githubusercontent.com/%s\n' "${1#https://gh.mccts.cn/raw/}" ;;
    https://gh.mccts.cn/*) printf 'https://github.com/%s\n' "${1#https://gh.mccts.cn/}" ;;
    *) printf '%s\n' "$1" ;;
  esac
}

cloudflare_url() {
  case "$1" in
    https://api.github.com/repos/Epresin/*) printf 'https://gh.mccts.cn/api/%s\n' "${1#https://api.github.com/}" ;;
    https://raw.githubusercontent.com/Epresin/*) printf 'https://gh.mccts.cn/raw/%s\n' "${1#https://raw.githubusercontent.com/}" ;;
    https://github.com/Epresin/*) printf 'https://gh.mccts.cn/%s\n' "${1#https://github.com/}" ;;
    *) return 1 ;;
  esac
}

request_download() {
  connect_timeout=5
  download_timeout="${3:-0}"
  read_timeout=10
  case "$1" in
    https://gh.mccts.cn/*) connect_timeout=1800; download_timeout=1800; read_timeout=1800 ;;
  esac
  if command -v curl >/dev/null 2>&1; then
    progress_flag=--progress-bar
    [ "$2" != "-" ] || progress_flag=--silent
    curl --connect-timeout "$connect_timeout" --max-time "$download_timeout" --speed-time 10 --speed-limit "${4:-0}" -fSL "$progress_flag" "$1" -o "$2"
  elif command -v wget >/dev/null 2>&1; then
    progress_flag=--progress=bar:force
    [ "$2" != "-" ] || progress_flag=--quiet
    wget --connect-timeout="$connect_timeout" --read-timeout="$read_timeout" --tries=1 "$progress_flag" -O "$2" "$1"
  else
    echo "curl or wget is required to install Codex." >&2
    return 1
  fi
}

download_file() {
  primary="$(github_url "$1")"
  if request_download "$primary" "$2" 0 262144; then return; fi
  fallback="$(cloudflare_url "$primary")" || return 1
  warn "GitHub download failed or stayed below 256 KiB/s for 10 seconds; retrying Cloudflare."
  request_download "$fallback" "$2"
}

download_text() {
  if text="$(request_download "$1" - 8)"; then
    printf '%s\n' "$text"
    return
  fi
  fallback="$(cloudflare_url "$1")" || return 1
  warn "GitHub metadata failed or timed out; retrying Cloudflare."
  request_download "$fallback" - 8
}

parse_release_metadata() {
  # Bound awk's record size so compact, single-line JSON stays fast on every
  # supported awk implementation. JSON strings cannot contain literal newlines,
  # so the record boundaries inserted by fold do not change the document.
  LC_ALL=C fold -b -w 4096 | LC_ALL=C awk '
    function finish_string(value) {
      if (object_depth == 1 && key == "tag_name") {
        print "tag_name\t" value
      } else if (object_depth == asset_object_depth) {
        if (key == "name") {
          asset_name = value
        } else if (key == "browser_download_url") {
          asset_url = value
        }
      }

      expecting_value = 0
      key = ""
    }

    {
      for (i = 1; i <= length($0); i++) {
        char = substr($0, i, 1)

        if (in_string) {
          if (escaped) {
            token = token "\\" char
            escaped = 0
          } else if (char == "\\") {
            escaped = 1
          } else if (char == "\"") {
            in_string = 0
            if (string_is_value) {
              finish_string(token)
            } else {
              pending_key = token
            }
          } else {
            token = token char
          }
          continue
        }

        if (char == "\"") {
          in_string = 1
          token = ""
          escaped = 0
          string_is_value = expecting_value
        } else if (char == ":" && pending_key != "") {
          key = pending_key
          pending_key = ""
          expecting_value = 1
        } else if (char == "{") {
          object_depth++
          if (assets_array_depth != 0 &&
              array_depth == assets_array_depth &&
              asset_object_depth == 0) {
            asset_object_depth = object_depth
            asset_name = ""
            asset_url = ""
          }
          expecting_value = 0
          key = ""
        } else if (char == "}") {
          if (object_depth == asset_object_depth) {
            if (asset_name != "" && asset_url != "") {
              print "asset\t" asset_name "\t" asset_url
            }
            asset_object_depth = 0
            asset_name = ""
            asset_url = ""
          }
          object_depth--
          expecting_value = 0
          key = ""
          pending_key = ""
        } else if (char == "[") {
          array_depth++
          if (expecting_value && key == "assets" && object_depth == 1) {
            assets_array_depth = array_depth
          }
          expecting_value = 0
          key = ""
        } else if (char == "]") {
          if (array_depth == assets_array_depth) {
            assets_array_depth = 0
          }
          array_depth--
          expecting_value = 0
          key = ""
          pending_key = ""
        } else if (char == ",") {
          expecting_value = 0
          key = ""
          pending_key = ""
        }
      }
    }

    END {
      if (in_string || object_depth != 0 || array_depth != 0) {
        exit 1
      }
    }
  '
}

resolve_release() {
  normalized_version="$(normalize_version "$RELEASE")"
  validate_version "$normalized_version"
  if [ "$normalized_version" = "latest" ]; then
    metadata_url="${RELEASES_API_URL%/}/latest"
  else
    metadata_url="${RELEASES_API_URL%/}/tags/rust-v$normalized_version"
  fi
  release_json="$(download_text "$metadata_url")"
  release_metadata="$(printf '%s\n' "$release_json" | parse_release_metadata)"
  release_tag="$(printf '%s\n' "$release_metadata" | awk -F '\t' '$1 == "tag_name" { print $2; exit }')"
  resolved_version="$(normalize_version "$release_tag")"
  validate_version "$resolved_version"
  select_release_assets
}

release_asset_url() {
  printf '%s\n' "$release_metadata" | awk -F '\t' -v asset="$1" '
    $1 == "asset" && $2 == asset { print $3; found = 1; exit }
    END { if (!found) exit 1 }
  '
}

select_release_assets() {
  asset="codex-package-$vendor_target.tar.gz"
  checksum_asset="codex-package_SHA256SUMS"
  install_layout="package"
  if ! download_url="$(release_asset_url "$asset")" ||
    ! checksum_url="$(release_asset_url "$checksum_asset")"; then
    echo "Could not find the standard Codex package for $vendor_target in release $resolved_version." >&2
    return 1
  fi
}

package_archive_digest() {
  asset="$1"
  manifest_path="$2"

  digest="$(awk -v asset="$asset" '
    $2 == asset && length($1) == 64 && $1 !~ /[^0-9a-fA-F]/ {
      print tolower($1)
      found = 1
      exit
    }
    END {
      if (!found) {
        exit 1
      }
    }
  ' "$manifest_path" 2>/dev/null || true)"

  if [ -z "$digest" ]; then
    echo "Could not find SHA-256 digest for $asset in codex-package_SHA256SUMS." >&2
    return 1
  fi

  printf '%s\n' "$digest"
}

file_sha256() {
  path="$1"

  if command -v sha256sum >/dev/null 2>&1; then
    sha256sum "$path" | awk '{print $1}'
    return
  fi

  if command -v shasum >/dev/null 2>&1; then
    shasum -a 256 "$path" | awk '{print $1}'
    return
  fi

  if command -v openssl >/dev/null 2>&1; then
    openssl dgst -sha256 "$path" | sed 's/^.*= //'
    return
  fi

  echo "sha256sum, shasum, or openssl is required to verify the Codex download." >&2
  exit 1
}

verify_archive_digest() {
  archive_path="$1"
  expected_digest="$2"
  actual_digest="$(file_sha256 "$archive_path")"

  if [ "$actual_digest" != "$expected_digest" ]; then
    echo "Downloaded Codex archive checksum did not match expected digest." >&2
    echo "expected: $expected_digest" >&2
    echo "actual:   $actual_digest" >&2
    return 1
  fi
}

require_command() {
  if ! command -v "$1" >/dev/null 2>&1; then
    echo "$1 is required to install Codex." >&2
    exit 1
  fi
}

pick_profile() {
  # Use the same shell-specific split Homebrew documents because there is no
  # universal startup file across macOS/Linux login and interactive shells.
  case "$os:${SHELL:-}" in
    darwin:*/zsh)
      printf '%s\n' "$HOME/.zprofile"
      ;;
    darwin:*/bash)
      printf '%s\n' "$HOME/.bash_profile"
      ;;
    linux:*/zsh)
      printf '%s\n' "$HOME/.zshrc"
      ;;
    linux:*/bash)
      printf '%s\n' "$HOME/.bashrc"
      ;;
    *)
      printf '%s\n' "$HOME/.profile"
      ;;
  esac
}

add_to_path() {
  path_action="already"
  path_profile=""

  case ":$PATH:" in
    *":$BIN_DIR:"*)
      if [ -z "$conflict_manager" ]; then
        return
      fi
      ;;
  esac

  profile="$(pick_profile)"
  path_profile="$profile"
  begin_marker="# >>> Codex installer >>>"
  end_marker="# <<< Codex installer <<<"
  path_line="export PATH=\"$BIN_DIR:\$PATH\""

  if [ -f "$profile" ] && grep -F "$begin_marker" "$profile" >/dev/null 2>&1; then
    if grep -F "$path_line" "$profile" >/dev/null 2>&1; then
      path_action="configured"
      return
    fi

    if grep -F "$end_marker" "$profile" >/dev/null 2>&1; then
      rewrite_path_block "$profile" "$begin_marker" "$end_marker" "$path_line"
      path_action="updated"
      return
    fi
  fi

  append_path_block "$profile" "$begin_marker" "$end_marker" "$path_line"
  path_action="added"
}

append_path_block() {
  profile="$1"
  begin_marker="$2"
  end_marker="$3"
  path_line="$4"

  {
    printf '\n%s\n' "$begin_marker"
    printf '%s\n' "$path_line"
    printf '%s\n' "$end_marker"
  } >>"$profile"
}

rewrite_path_block() {
  profile="$1"
  begin_marker="$2"
  end_marker="$3"
  path_line="$4"
  tmp_profile="$tmp_dir/profile.$$.tmp"

  awk -v begin="$begin_marker" -v end="$end_marker" -v line="$path_line" '
    BEGIN {
      in_block = 0
      replaced = 0
    }
    $0 == begin {
      if (!replaced) {
        print begin
        print line
        print end
        replaced = 1
      }
      in_block = 1
      next
    }
    in_block {
      if ($0 == end) {
        in_block = 0
      }
      next
    }
    {
      print
    }
    END {
      if (in_block != 0) {
        exit 1
      }
    }
  ' "$profile" >"$tmp_profile"
  mv "$tmp_profile" "$profile"
}

mkdir_lock_is_stale() {
  [ -d "$LOCK_DIR" ] || return 1

  pid="$(cat "$LOCK_DIR/pid" 2>/dev/null || true)"
  started_at="$(cat "$LOCK_DIR/started_at" 2>/dev/null || true)"
  now="$(date +%s 2>/dev/null || printf '0')"

  case "$started_at" in
    ''|*[!0-9]*)
      started_at=0
      ;;
  esac

  if [ -n "$pid" ] && kill -0 "$pid" 2>/dev/null; then
    return 1
  fi

  if [ "$started_at" -eq 0 ] || [ "$now" -eq 0 ]; then
    return 0
  fi

  [ $((now - started_at)) -ge "$LOCK_STALE_AFTER_SECS" ]
}

acquire_install_lock() {
  mkdir -p "$STANDALONE_ROOT"

  if [ "$os" = "darwin" ] && command -v lockf >/dev/null 2>&1; then
    : >>"$LOCK_FILE"
    exec 9<>"$LOCK_FILE"
    lockf 9
    lock_kind="lockf"
    return
  fi

  if command -v flock >/dev/null 2>&1; then
    exec 9>"$LOCK_FILE"
    flock 9
    lock_kind="flock"
    return
  fi

  while ! mkdir "$LOCK_DIR" 2>/dev/null; do
    if mkdir_lock_is_stale; then
      warn "Removing stale installer lock at $LOCK_DIR"
      rm -rf "$LOCK_DIR"
      continue
    fi
    sleep 1
  done

  printf '%s\n' "$$" >"$LOCK_DIR/pid"
  date +%s >"$LOCK_DIR/started_at" 2>/dev/null || true
  lock_kind="mkdir"
}

release_install_lock() {
  if [ "$lock_kind" = "mkdir" ]; then
    rm -rf "$LOCK_DIR" 2>/dev/null || true
  elif [ "$lock_kind" = "flock" ] || [ "$lock_kind" = "lockf" ]; then
    exec 9>&- 2>/dev/null || true
  fi
  lock_kind=""
}

cleanup_stale_install_artifacts() {
  mkdir -p "$RELEASES_DIR" "$STANDALONE_ROOT"

  find "$RELEASES_DIR" -mindepth 1 -maxdepth 1 -name '.staging.*' -exec rm -rf {} +
  find "$STANDALONE_ROOT" -mindepth 1 -maxdepth 1 -name '.current.*' -exec rm -f {} +

  if [ "$DAEMON_ONLY" != "1" ] && [ -d "$BIN_DIR" ]; then
    find "$BIN_DIR" -mindepth 1 -maxdepth 1 -name '.codex.*' -exec rm -f {} +
  fi
}

replace_path_with_symlink() {
  link_path="$1"
  link_target="$2"
  tmp_link="$3"

  rm -f "$tmp_link"
  ln -s "$link_target" "$tmp_link"

  if mv -Tf "$tmp_link" "$link_path" 2>/dev/null; then
    return
  fi

  if mv -hf "$tmp_link" "$link_path" 2>/dev/null; then
    return
  fi

  rm -f "$link_path"
  mv -f "$tmp_link" "$link_path"
}

version_from_binary() {
  codex_path="$1"

  if [ ! -x "$codex_path" ]; then
    return 1
  fi

  "$codex_path" --version 2>/dev/null | sed -n 's/.* \([0-9][0-9A-Za-z.+-]*\)$/\1/p' | head -n 1
}

current_installed_version() {
  version="$(version_from_binary "$CURRENT_LINK/bin/codex" || true)"
  if [ -n "$version" ]; then
    printf '%s\n' "$version"
    return 0
  fi

  version="$(version_from_binary "$CURRENT_LINK/codex" || true)"
  if [ -n "$version" ]; then
    printf '%s\n' "$version"
    return 0
  fi

  return 0
}

resolve_existing_codex() {
  command -v codex 2>/dev/null || true
}

classify_existing_codex() {
  existing_path="$1"

  if [ -z "$existing_path" ] || [ "$existing_path" = "$BIN_PATH" ]; then
    return 1
  fi

  case "$existing_path" in
    /opt/homebrew/* | /usr/local/*)
      if [ "$os" = "darwin" ]; then
        printf 'brew\n'
        return 0
      fi
      ;;
  esac

  if [ -f "$existing_path" ] && grep -F "#!/usr/bin/env node" "$existing_path" >/dev/null 2>&1; then
    case "$existing_path" in
      *".bun"*)
        printf 'bun\n'
        ;;
      *)
        printf 'npm\n'
        ;;
    esac
    return 0
  fi

  return 1
}

prompt_yes_no() {
  prompt="$1"

  case "$NON_INTERACTIVE" in
    1 | [Tt][Rr][Uu][Ee] | [Yy][Ee][Ss])
      return 1
      ;;
  esac

  if ( : </dev/tty ) 2>/dev/null; then
    printf '%s [y/N] ' "$prompt" >/dev/tty
    if ! IFS= read -r answer </dev/tty; then
      return 1
    fi
  elif [ -t 0 ]; then
    printf '%s [y/N] ' "$prompt"
    if ! IFS= read -r answer; then
      return 1
    fi
  else
    return 1
  fi

  case "$answer" in
    y | Y | yes | YES)
      return 0
      ;;
    *)
      return 1
      ;;
  esac
}

print_launch_instructions() {
  case "$path_action" in
    added)
      step "Current terminal: export PATH=\"$BIN_DIR:\$PATH\" && codex"
      step "Future terminals: open a new terminal and run: codex"
      step "PATH was added to $path_profile"
      ;;
    updated)
      step "Current terminal: export PATH=\"$BIN_DIR:\$PATH\" && codex"
      step "Future terminals: open a new terminal and run: codex"
      step "PATH was updated in $path_profile"
      ;;
    configured)
      step "Current terminal: export PATH=\"$BIN_DIR:\$PATH\" && codex"
      step "Future terminals: open a new terminal and run: codex"
      step "PATH is already configured in $path_profile"
      ;;
    *)
      step "Current terminal: codex"
      step "Future terminals: open a new terminal and run: codex"
      ;;
  esac
}

maybe_launch_codex_now() {
  if prompt_yes_no "Start Codex now?"; then
    step "Launching Codex"
    "$BIN_PATH"
  fi
}

detect_conflicting_install() {
  existing_path="$(resolve_existing_codex)"
  manager="$(classify_existing_codex "$existing_path" || true)"

  if [ -z "$manager" ]; then
    return
  fi

  conflict_manager="$manager"
  conflict_path="$existing_path"
  step "Detected existing $manager-managed Codex at $existing_path"
  warn "Multiple managed Codex installs can be ambiguous because PATH order decides which one runs."
}

handle_conflicting_install() {
  if [ -z "$conflict_manager" ]; then
    return
  fi

  case "$conflict_manager" in
    brew)
      uninstall_cmd="brew uninstall --cask codex"
      ;;
    bun)
      uninstall_cmd="bun remove -g @openai/codex"
      ;;
    *)
      uninstall_cmd="npm uninstall -g @openai/codex"
      ;;
  esac

  if prompt_yes_no "Uninstall the existing $conflict_manager-managed Codex now?"; then
    step "Running: $uninstall_cmd"
    if ! sh -c "$uninstall_cmd"; then
      warn "Failed to uninstall the existing $conflict_manager-managed Codex. Continuing with the standalone install."
    fi
  else
    warn "Leaving the existing $conflict_manager-managed Codex installed. PATH order will determine which codex runs."
  fi
}

install_package_release() {
  release_dir="$1"
  archive_path="$2"
  stage_release="$RELEASES_DIR/.staging.$(basename "$release_dir").$$"

  mkdir -p "$RELEASES_DIR"
  rm -rf "$stage_release"
  mkdir -p "$stage_release"
  tar -xzf "$archive_path" -C "$stage_release"
  chmod 0755 \
    "$stage_release/bin/codex" \
    "$stage_release/bin/codex-code-mode-host" \
    "$stage_release/codex-path/rg"
  if [ -f "$stage_release/codex-resources/bwrap" ]; then
    chmod 0755 "$stage_release/codex-resources/bwrap"
  fi
  ln -sf "bin/codex" "$stage_release/codex"

  if [ -e "$release_dir" ] || [ -L "$release_dir" ]; then
    rm -rf "$release_dir"
  fi
  mv "$stage_release" "$release_dir"
}


release_dir_is_complete() {
  release_dir="$1"
  expected_version="$2"
  expected_target="$3"
  layout="$4"

  [ -d "$release_dir" ] &&
    [ "$(basename "$release_dir")" = "$expected_version-$expected_target" ] ||
    return 1

  case "$layout" in
    package)
      [ -f "$release_dir/codex-package.json" ] &&
        [ -x "$release_dir/bin/codex" ] &&
        [ -x "$release_dir/bin/codex-code-mode-host" ] &&
        [ -x "$release_dir/codex" ] &&
        [ -x "$release_dir/codex-path/rg" ] ||
        return 1
      ;;
    legacy-platform-npm)
      [ -x "$release_dir/codex" ] &&
        [ -x "$release_dir/codex-resources/rg" ] ||
        return 1
      ;;
    *)
      return 1
      ;;
  esac

  case "$layout:$expected_target" in
    package:*linux* | legacy-platform-npm:*linux*)
      [ -x "$release_dir/codex-resources/bwrap" ] || return 1
      ;;
  esac

  installed_version="$(version_from_binary "$release_dir/bin/codex" || version_from_binary "$release_dir/codex" || true)"
  [ "$installed_version" = "$expected_version" ]
}

update_current_link() {
  release_dir="$1"
  tmp_link="$STANDALONE_ROOT/.current.$$"

  replace_path_with_symlink "$CURRENT_LINK" "$release_dir" "$tmp_link"
}

release_codex_relative_path() {
  release_dir="$1"

  if [ -x "$release_dir/bin/codex" ]; then
    printf 'bin/codex\n'
  else
    printf 'codex\n'
  fi
}

update_visible_command() {
  release_dir="$1"
  mkdir -p "$BIN_DIR"
  tmp_link="$BIN_DIR/.codex.$$"
  codex_relative_path="$(release_codex_relative_path "$release_dir")"

  replace_path_with_symlink "$BIN_PATH" "$CURRENT_LINK/$codex_relative_path" "$tmp_link"

  if [ "$os" = "darwin" ] && [ -x "$release_dir/bin/codex-code-mode-host" ]; then
    replace_path_with_symlink \
      "$CODE_MODE_HOST_BIN_PATH" \
      "$CURRENT_LINK/bin/codex-code-mode-host" \
      "$tmp_link"
  elif [ "$(readlink "$CODE_MODE_HOST_BIN_PATH" 2>/dev/null || true)" = \
    "$CURRENT_LINK/bin/codex-code-mode-host" ]; then
    rm -f "$CODE_MODE_HOST_BIN_PATH"
  fi
}

verify_visible_command() {
  "$BIN_PATH" --version >/dev/null
  if [ "$os" = "darwin" ] && [ "$install_layout" = "package" ]; then
    [ -x "$CODE_MODE_HOST_BIN_PATH" ]
  fi
}

parse_args "$@"

require_command mktemp
require_command tar

case "$(uname -s)" in
  Darwin)
    os="darwin"
    ;;
  Linux)
    os="linux"
    ;;
  *)
    echo "install.sh supports macOS and Linux. Use install.ps1 on Windows." >&2
    exit 1
    ;;
esac

case "$(uname -m)" in
  x86_64 | amd64)
    arch="x86_64"
    ;;
  arm64 | aarch64)
    arch="aarch64"
    ;;
  *)
    echo "Unsupported architecture: $(uname -m)" >&2
    exit 1
    ;;
esac

if [ "$os" = "darwin" ] && [ "$arch" = "x86_64" ]; then
  if [ "$(sysctl -n sysctl.proc_translated 2>/dev/null || true)" = "1" ]; then
    arch="aarch64"
  fi
fi

if [ "$os" = "darwin" ]; then
  if [ "$arch" = "aarch64" ]; then
    npm_tag="darwin-arm64"
    vendor_target="aarch64-apple-darwin"
    platform_label="macOS (Apple Silicon)"
  else
    npm_tag="darwin-x64"
    vendor_target="x86_64-apple-darwin"
    platform_label="macOS (Intel)"
  fi
else
  if [ "$arch" = "aarch64" ]; then
    npm_tag="linux-arm64"
    vendor_target="aarch64-unknown-linux-musl"
    platform_label="Linux (ARM64)"
  else
    npm_tag="linux-x64"
    vendor_target="x86_64-unknown-linux-musl"
    platform_label="Linux (x64)"
  fi
fi

resolve_release
release_name="$resolved_version-$vendor_target"
release_dir="$RELEASES_DIR/$release_name"
current_version="$(current_installed_version)"

if [ -n "$current_version" ] && [ "$current_version" != "$resolved_version" ]; then
  step "Updating Codex CLI from $current_version to $resolved_version"
elif [ -n "$current_version" ]; then
  step "Updating Codex CLI"
else
  step "Installing Codex CLI"
fi
step "Detected platform: $platform_label"
step "Resolved version: $resolved_version"

if [ "$DAEMON_ONLY" != "1" ]; then
  detect_conflicting_install
fi

tmp_dir="$(mktemp -d)"
cleanup() {
  release_install_lock
  if [ -n "$tmp_dir" ]; then
    rm -rf "$tmp_dir"
  fi
}
trap cleanup EXIT
trap 'exit 130' INT
trap 'exit 143' TERM

acquire_install_lock
if [ "${CODEX_INSTALL_DEFER_SELECTION:-0}" = "1" ] &&
  { [ -e "$STANDALONE_ROOT/current" ] || [ -L "$STANDALONE_ROOT/current" ]; }; then
  echo "A dedicated daemon is already selected; retry the update." >&2
  exit 1
fi
updater_record="$CODEX_HOME_DIR/app-server-daemon/app-server-updater.pid"
if [ "$DAEMON_ONLY" = "1" ]; then
  updater_record="$CODEX_HOME_DIR/app-server-daemon/daemon-updater.pid"
fi
old_updater_parent="false"
if [ "${CODEX_INSTALL_IF_LATEST:-}" != "1" ] && [ "${CODEX_INSTALL_IF_CURRENT:-}" != "1" ] && [ -f "$updater_record" ]; then
  updater_pid="$(sed -n 's/.*"pid"[[:space:]]*:[[:space:]]*\([0-9][0-9]*\).*/\1/p' "$updater_record" | head -n 1)"
  recorded_start="$(sed -n 's/.*"processStartTime"[[:space:]]*:[[:space:]]*"\([^"]*\)".*/\1/p' "$updater_record" | head -n 1)"
  if [ -r "/proc/$$/stat" ]; then
    parent_pid="$(sed 's/^.*) //' "/proc/$$/stat" | awk '{ print $2 }')"
  else
    parent_pid="$(ps -p "$$" -o ppid= 2>/dev/null)" || parent_pid=""
    parent_pid="$(printf '%s' "$parent_pid" | tr -d ' ')"
  fi
  if [ -n "$updater_pid" ] && [ "$updater_pid" = "$parent_pid" ]; then
    actual_details="$(ps -p "$updater_pid" -o stat= -o lstart= 2>/dev/null)" || actual_details=""
    actual_start="$(printf '%s' "$actual_details" | sed 's/^[^[:space:]]*[[:space:]]*//; s/[[:space:]]*$//')"
    if [ -n "$recorded_start" ] && [ "$recorded_start" = "$actual_start" ]; then
      old_updater_parent="true"
    fi
  fi
  if [ "$RELEASE" = "latest" ] && [ -n "$updater_pid" ] &&
    { [ -z "$parent_pid" ] || { [ "$updater_pid" = "$parent_pid" ] &&
      { [ -z "$recorded_start" ] || [ -z "$actual_start" ]; }; }; } &&
    kill -0 "$updater_pid" 2>/dev/null; then
    warn "Cannot verify whether an older updater launched this installer; skipping latest update."
    exit 0
  fi
fi
if [ "${CODEX_INSTALL_IF_LATEST:-}" = "1" ] || [ "${CODEX_INSTALL_IF_CURRENT:-}" = "1" ] || [ "$old_updater_parent" = "true" ]; then
  guarded_release="${CODEX_UPDATE_FROM_RELEASE:-}"
  if [ "$old_updater_parent" = "true" ]; then
    guarded_release="$(cat "$AUTO_UPDATE_VERSION" 2>/dev/null || true)"
  fi
  current_release_dir="$(cd -P "$CURRENT_LINK" 2>/dev/null && pwd)" || exit 0
  releases_dir="$(cd -P "$RELEASES_DIR" 2>/dev/null && pwd)" || exit 0
  if [ "$RELEASE" != "latest" ] || [ -z "$guarded_release" ] ||
    [ "$current_release_dir" != "$releases_dir/$guarded_release" ]; then
    if [ "${CODEX_INSTALL_IF_CURRENT:-}" = "1" ]; then
      echo "Daemon selection changed; retry the update." >&2
      exit 1
    fi
    exit 0
  fi
  # An explicit daemon update may leave a local or pinned release. Scheduled
  # updates still require the selected release to follow the latest channel.
  if [ "${CODEX_INSTALL_IF_CURRENT:-}" != "1" ] &&
    [ "$(cat "$AUTO_UPDATE_VERSION" 2>/dev/null || true)" != "$guarded_release" ]; then
    exit 0
  fi
fi
cleanup_stale_install_artifacts

if ! release_dir_is_complete "$release_dir" "$resolved_version" "$vendor_target" "$install_layout"; then
  if [ -e "$release_dir" ] || [ -L "$release_dir" ]; then
    if [ "$DAEMON_ONLY" = "1" ]; then
      echo "Refusing to overwrite existing daemon release $release_dir." >&2
      exit 1
    fi
    warn "Found incomplete existing release at $release_dir; reinstalling."
  fi

  archive_path="$tmp_dir/$asset"
  checksum_path="$tmp_dir/$checksum_asset"

  step "Downloading Codex CLI"
  download_file "$checksum_url" "$checksum_path"
  expected_digest="$(package_archive_digest "$asset" "$checksum_path")"
  download_file "$download_url" "$archive_path"
  verify_archive_digest "$archive_path" "$expected_digest"

  step "Installing standalone package to $release_dir"
  install_package_release "$release_dir" "$archive_path"

fi
if ! release_dir_is_complete "$release_dir" "$resolved_version" "$vendor_target" "$install_layout"; then
  echo "Installed Codex command did not report expected version $resolved_version." >&2
  exit 1
fi
if [ "$DAEMON_ONLY" = "1" ] && [ "${CODEX_INSTALL_DEFER_SELECTION:-0}" != "1" ]; then
  installed_codex="$release_dir/codex"
  if [ "$install_layout" = "package" ]; then
    installed_codex="$release_dir/bin/codex"
  fi
  if ! "$installed_codex" app-server daemon pid-update-loop --check-package-ownership >/dev/null 2>&1; then
    echo "The production release does not support daemon-owned packages; the current selection was left unchanged." >&2
    exit 1
  fi
fi
update_current_link "$release_dir"
if [ "$RELEASE" = "latest" ]; then
  printf '%s' "$release_name" > "$AUTO_UPDATE_VERSION.tmp.$$"
  mv -f "$AUTO_UPDATE_VERSION.tmp.$$" "$AUTO_UPDATE_VERSION"
else
  rm -f "$AUTO_UPDATE_VERSION"
fi
if [ "$DAEMON_ONLY" = "1" ]; then
  release_install_lock
  exit 0
fi
update_visible_command "$release_dir"
add_to_path
verify_visible_command
release_install_lock
handle_conflicting_install

case "$path_action" in
  added)
    print_launch_instructions
    ;;
  updated)
    print_launch_instructions
    ;;
  configured)
    print_launch_instructions
    ;;
  *)
    step "$BIN_DIR is already on PATH"
    print_launch_instructions
    ;;
esac

printf 'Codex CLI %s installed successfully.\n' "$resolved_version"
maybe_launch_codex_now
