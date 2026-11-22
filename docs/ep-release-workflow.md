# EP 版本交付流程

本仓库的发布由精简的 GitHub Actions 工作流 [.github/workflows/ep-release.yml](../.github/workflows/ep-release.yml) 自动完成，在免费公开仓库 runner 上并行构建 Linux (`x86_64-unknown-linux-musl`) 与 Windows (`x86_64-pc-windows-msvc`) 并发布 GitHub Release。

## 版本规则

正式 fork 版本为 `X.Y.Z-epr.N`，标签为 `rust-vX.Y.Z-epr.N`（`N >= 1`）：

- 同一官方基础递增加 1：`0.171.0-epr.1 -> 0.171.0-epr.2`
- 切换官方基础重置为 1：`0.170.0-epr.1 -> 0.171.0-epr.1`

提交前运行版本护栏校验：

```sh
python3 scripts/ep_release_version.py --previous PREVIOUS_FORK_VERSION --upstream OFFICIAL_TAG --check-workspace
```

## 发版步骤

1. **核实历史与目标版本**：查看 `Epresin/codex` 已发布的非 draft/非 prerelease Release，确认上一版本与目标版本，确保无同名已发布 tag。
2. **合并上游或实现改动**：保留 fork 功能；升级官方基础时更新 `codex-rs/Cargo.toml` 版本并将 `codex-rs/Cargo.lock` 中所有继承 workspace 版本的 crate 同步到新版本。
3. **本地轻量校验**：运行版本护栏 `--check-workspace` 与相关单测（如 Python 安装器测试）。
4. **提交并推送 `origin/ep`**：冻结最终提交 SHA。
5. **触发自动构建与发布**：
   - 创建并推送 annotated tag：`git tag -a rust-vX.Y.Z-epr.N -m "Release X.Y.Z-epr.N" && git push origin rust-vX.Y.Z-epr.N`（或在 GitHub Actions 页面手动触发 `ep-release`）。
   - `ep-release.yml` 自动完成：
     - `validate`：校验版本格式、`Cargo.lock` 对齐、Python 测试并自动读取 `codex-rs/rust-toolchain.toml`；
     - `build-linux`（`ubuntu-latest`）：musl 构建 `bwrap`、`codex`、`codex-code-mode-host`、`codex-exec-server`，校验 `--version` 并打包 `.tar.gz`/`.tar.zst`；
     - `build-windows`（`windows-latest`）：以 `core.autocrlf=true` 签出并校验 `codex-rs/state` SQL 为 CRLF，MSVC 构建并校验 `--version`，打包 `.tar.gz`/`.tar.zst`；
     - `publish`：合并生成覆盖 4 个归档的 `codex-package_SHA256SUMS`，从 Git blob 提取 LF 版 `install.sh` 与 `install.ps1`，写入 `SOURCE_COMMIT.txt`，以 draft 上传全部资产后发布为公开 Latest。
6. **读回验证**：用 `gh release view rust-vX.Y.Z-epr.N --repo Epresin/codex` 确认公开 Latest 状态及 Linux/Windows 资产齐全。

> 如需本机离线单独构建 Windows 包，仍可按需参考 [ep-windows-build.md](ep-windows-build.md)。
