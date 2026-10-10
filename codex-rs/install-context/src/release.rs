//! The EP release source shared by CLI update entrypoints.

pub const REPOSITORY_URL: &str = "https://gitee.com/epresin/codex";
pub const RELEASES_URL: &str = "https://gitee.com/epresin/codex/releases";
pub const LATEST_RELEASE_URL: &str = "https://gitee.com/api/v5/repos/epresin/codex/releases/latest";
pub const VERSION_CACHE_FILE: &str = "ep-version.json";
pub const UNIX_INSTALLER_URL: &str =
    "https://gitee.com/epresin/codex/raw/main/scripts/install/install.sh";
pub const WINDOWS_INSTALLER_URL: &str =
    "https://gitee.com/epresin/codex/raw/main/scripts/install/install.ps1";
pub const UNIX_UPDATE_COMMAND: &str = "curl -fsSL https://gitee.com/epresin/codex/raw/main/scripts/install/install.sh | CODEX_NON_INTERACTIVE=1 sh";
pub const WINDOWS_UPDATE_COMMAND: &str = "$env:CODEX_NON_INTERACTIVE=1; irm https://gitee.com/epresin/codex/raw/main/scripts/install/install.ps1 | iex";

pub fn version_from_tag(tag: &str) -> Option<&str> {
    tag.strip_prefix("rust-v")
        .or_else(|| tag.strip_prefix("api-key-compat-v"))
}

pub fn is_newer(latest: &str, current: &str) -> Option<bool> {
    let latest = semver::Version::parse(latest.trim()).ok()?;
    let current = semver::Version::parse(current.trim()).ok()?;
    Some(latest > current)
}
