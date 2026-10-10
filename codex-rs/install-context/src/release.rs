//! The EP release source shared by CLI update entrypoints.

pub const REPOSITORY_URL: &str = "https://github.com/Epresin/codex";
pub const RELEASES_URL: &str = "https://github.com/Epresin/codex/releases";
pub const LATEST_RELEASE_URL: &str = "https://api.github.com/repos/Epresin/codex/releases/latest";
pub const LATEST_RELEASE_FALLBACK_URL: &str =
    "https://gh.mccts.cn/api/repos/Epresin/codex/releases/latest";
pub const RELEASE_REQUEST_TIMEOUT: std::time::Duration = std::time::Duration::from_secs(8);
pub const VERSION_CACHE_FILE: &str = "ep-version.json";
pub const UNIX_INSTALLER_URL: &str =
    "https://raw.githubusercontent.com/Epresin/codex/ep/scripts/install/install.sh";
pub const UNIX_INSTALLER_FALLBACK_URL: &str =
    "https://gh.mccts.cn/raw/Epresin/codex/ep/scripts/install/install.sh";
pub const WINDOWS_INSTALLER_URL: &str =
    "https://raw.githubusercontent.com/Epresin/codex/ep/scripts/install/install.ps1";
pub const WINDOWS_INSTALLER_FALLBACK_URL: &str =
    "https://gh.mccts.cn/raw/Epresin/codex/ep/scripts/install/install.ps1";
pub const UNIX_UPDATE_COMMAND: &str = r#"s=$(curl -fsSL --connect-timeout 5 --max-time 8 https://raw.githubusercontent.com/Epresin/codex/ep/scripts/install/install.sh) || s=$(curl -fsSL --connect-timeout 5 --max-time 8 https://gh.mccts.cn/raw/Epresin/codex/ep/scripts/install/install.sh) || exit; printf '%s\n' "$s" | CODEX_NON_INTERACTIVE=1 sh"#;
pub const WINDOWS_UPDATE_COMMAND: &str = r#"$s = & curl.exe -fsSL --connect-timeout 5 --max-time 8 https://raw.githubusercontent.com/Epresin/codex/ep/scripts/install/install.ps1; if ($LASTEXITCODE -ne 0) { $s = & curl.exe -fsSL --connect-timeout 5 --max-time 8 https://gh.mccts.cn/raw/Epresin/codex/ep/scripts/install/install.ps1 }; if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }; $env:CODEX_NON_INTERACTIVE=1; ($s -join "`n") | iex"#;

pub fn version_from_tag(tag: &str) -> Option<&str> {
    tag.strip_prefix("rust-v")
        .or_else(|| tag.strip_prefix("api-key-compat-v"))
}

pub fn is_newer(latest: &str, current: &str) -> Option<bool> {
    let latest = semver::Version::parse(latest.trim()).ok()?;
    let current = semver::Version::parse(current.trim()).ok()?;
    Some(latest > current)
}
