use codex_install_context::release;

/// The release installer, or synchronization of the local background server.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum UpdateAction {
    Daemon(DaemonUpdateSource),
    StandaloneUnix,
    StandaloneWindows,
}

impl UpdateAction {
    pub fn command_args(self) -> (&'static str, &'static [&'static str]) {
        match self {
            Self::Daemon(source) => ("codex", source.command_args()),
            Self::StandaloneUnix => ("sh", &["-c", release::UNIX_UPDATE_COMMAND]),
            Self::StandaloneWindows => (
                "powershell",
                &[
                    "-ExecutionPolicy",
                    "Bypass",
                    "-c",
                    release::WINDOWS_UPDATE_COMMAND,
                ],
            ),
        }
    }

    pub fn command_str(self) -> String {
        let (command, args) = self.command_args();
        shlex::try_join(std::iter::once(command).chain(args.iter().copied()))
            .unwrap_or_else(|_| format!("{command} {}", args.join(" ")))
    }
}

#[cfg(any(not(debug_assertions), test))]
pub fn get_update_action() -> Option<UpdateAction> {
    Some(if cfg!(windows) {
        UpdateAction::StandaloneWindows
    } else {
        UpdateAction::StandaloneUnix
    })
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn update_uses_the_ep_installer() {
        assert_eq!(
            UpdateAction::StandaloneUnix.command_args(),
            ("sh", &["-c", release::UNIX_UPDATE_COMMAND][..])
        );
        assert_eq!(
            UpdateAction::StandaloneWindows.command_args(),
            (
                "powershell",
                &[
                    "-ExecutionPolicy",
                    "Bypass",
                    "-c",
                    release::WINDOWS_UPDATE_COMMAND
                ][..]
            )
        );
        assert!(get_update_action().is_some());
    }
}

/// Package source explicitly selected by the user in the daemon menu.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum DaemonUpdateSource {
    PublicStable,
    ThisCli,
}

impl DaemonUpdateSource {
    pub fn command_args(self) -> &'static [&'static str] {
        match self {
            Self::PublicStable => &["app-server", "daemon", "update"],
            Self::ThisCli => &["app-server", "daemon", "update", "--from-cli", "--yes"],
        }
    }
}
