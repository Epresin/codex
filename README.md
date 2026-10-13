> **EP fork:** This repository preserves official Codex history and adds API-key/custom-base-URL compatibility, HTTP/SSE defaults, and WSL image paste. Versions carry `-ep.N`. Updates use this repository's Releases and standard standalone packages, not official npm/Homebrew/CDN channels. See [the fork notes](docs/api-key-compat.md) for installation and maintenance.

<p align="center"><strong>Codex CLI</strong> is a coding agent from OpenAI that runs locally on your computer.
<p align="center">
  <img src="https://github.com/openai/codex/blob/main/.github/codex-cli-splash.png" alt="Codex CLI splash" width="80%" />
</p>
</br>
If you want Codex in your code editor (VS Code, Cursor, Windsurf), <a href="https://developers.openai.com/codex/ide">install in your IDE.</a>
</br>If you want the desktop app experience, run <code>codex app</code> or visit <a href="https://chatgpt.com/codex?app-landing-page=true">the Codex App page</a>.
</br>If you are looking for the <em>cloud-based agent</em> from OpenAI, <strong>Codex Web</strong>, go to <a href="https://chatgpt.com/codex">chatgpt.com/codex</a>.</p>

---

## Quickstart

### Installing and running Codex EP

This is the public `Epresin/codex` fork of `openai/codex`. Our maintained branch
is `ep`; `main` retains the upstream line. Install the EP Linux x86_64 package
(including WSL) or Windows x86_64 package from this repository's Releases. GitHub is tried first, with
Cloudflare fallback if it fails or is slow:

```sh
if s=$(curl -fsSL --connect-timeout 5 --max-time 8 https://raw.githubusercontent.com/Epresin/codex/ep/scripts/install/install.sh) ||
   s=$(curl -fsSL --connect-timeout 1800 --max-time 1800 https://gh.mccts.cn/raw/Epresin/codex/ep/scripts/install/install.sh); then
  printf '%s\n' "$s" | CODEX_NON_INTERACTIVE=1 sh
fi
```

Then run `codex --version` and `codex`. The current release is `0.162.1-ep.6`.
Use `codex update` for later releases. Existing configuration and authentication
are preserved. Linux x86_64 musl and Windows x86_64 MSVC packages are provided;
installing official npm/Homebrew packages would install upstream Codex, not EP.

For API-key/custom-base-URL setup, package contents, and maintenance, see
[the fork notes](docs/api-key-compat.md). Standard packages are available in
[this fork's Releases](https://github.com/Epresin/codex/releases).

**EP.3 update policy:** Update checks, installer bootstrap, and package downloads
try GitHub first, then the Cloudflare proxy on failure or slow transfer. The
previous EP.2 binary used a legacy Gitee bootstrap; EP.3 is a fresh build and
has no Gitee updater dependency. Existing model/authentication settings are
unrelated to this release-source change.

### Using Codex with your ChatGPT plan

Run `codex` and select **Sign in with ChatGPT**. We recommend signing into your ChatGPT account to use Codex as part of your Plus, Pro, Business, Edu, or Enterprise plan. [Learn more about what's included in your ChatGPT plan](https://help.openai.com/en/articles/11369540-codex-in-chatgpt).

You can also use Codex with an API key, but this requires [additional setup](https://developers.openai.com/codex/auth#sign-in-with-an-api-key).

## Docs

- [**Codex Documentation**](https://developers.openai.com/codex)
- [**Contributing**](./docs/contributing.md)
- [**Installing & building**](./docs/install.md)
- [**Open source fund**](./docs/open-source-fund.md)

This repository is licensed under the [Apache-2.0 License](LICENSE).
