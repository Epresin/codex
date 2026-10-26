# EP 版本交付流程

本项目的日常请求以完整交付为目标，而不只是修改文件。根目录 `AGENTS.md` 是给 Codex
的默认指令；本文说明版本计算、既有构建入口和 GitHub 发布顺序。纯讨论/调研不发版，
“只改代码”“先别发布”等明确限制优先于默认流程。

## 用户只需说明要做什么

以下请求都默认包含必要检查、版本升级、提交、推送和 GitHub Release：

- “修复 Windows Terminal 图片预览，改动尽量小，不要多余测试。”
- “新增这个功能：……，保留现有个人修改。”
- “合并官方 0.165.0，保留我们的修改，大冲突告诉我。”
- “升级到最新官方稳定版。”（必须先核实实际版本。）
- “继续上次发布。”（恢复原版本，不重新分配修订号。）

仅本地修改可以说“先只改代码，不提交、不发布”。本机升级可以额外说
“发布后更新本机 Windows Codex”或明确要求更新 WSL 内的 Linux 安装。

## 版本计算与防误用

把版本拆成两部分：`官方基础 X.Y.Z` 与 `该基础内的修订 epr.N`。

| 上一发布版 | 目标官方基础 | 下一新发布版 |
| --- | --- | --- |
| `0.164.0-epr.1` | `0.164.0` | `0.164.0-epr.2` |
| `0.164.0-epr.9` | `0.164.0` | `0.164.0-epr.10` |
| `0.164.0-epr.3` | `0.165.0` | `0.165.0-epr.1` |
| `0.164.0-epr.3` | `0.164.1` | `0.164.1-epr.1` |
| `0.165.0-epr.1` | `0.165.0` | `0.165.0-epr.2` |

版本示例只说明规则，不声明这些版本已经发布。先从 `Epresin/codex` 的已发布、
非 draft、非 prerelease 的 fork Releases 核实历史。若目标官方基础已有发布，选该基础
下最大的数值修订号继续；目标基础首次发布时，从旧基础升级才重置为 1。
不要把官方 tag、工作区中已改过的版本、draft 或失败构建当作新发布的上一版。

在 `ep` 分支核实 `origin`/`upstream` 的身份，读取现有远端分支、标签和 Releases；
可使用已认证的 GitHub CLI/API。缺少远端信息时不能谎称编号无冲突。
不要用 `git describe --tags --abbrev=0` 代替 fork 发布历史：合并后它可能选到官方 tag。

版本护栏是纯本地 Python 3.10+ 工具，不联网、不改文件、不提交或发布：

```sh
# 同基础递增，输出 0.164.0-epr.4。
python scripts/ep_release_version.py --previous 0.164.0-epr.3 --upstream rust-v0.164.0

# 官方基础变化，输出 0.165.0-epr.1，而不是 epr.3/epr.4。
python scripts/ep_release_version.py --previous 0.164.0-epr.3 --upstream rust-v0.165.0

# 错误的跨基础修订号必须以非零退出码拒绝。
python scripts/ep_release_version.py --previous 0.164.0-epr.3 --upstream rust-v0.165.0 --check 0.165.0-epr.4

# 更新 Cargo.toml 后，在提交和发布前检查实际 workspace 版本。
python scripts/ep_release_version.py --previous PREVIOUS_FORK_VERSION --upstream OFFICIAL_TAG --check-workspace
```

护栏接受历史 `-ep.N` 作为 previous，但新输出/候选只允许 `-epr.N`，拒绝基础降级、
缺失 patch 段、预览版本和无效修订号。它防止错误的版本运算，不认证调用方提供的历史，
也不替代远端重名检查、Cargo.lock 检查或二进制来源验证。

## 执行顺序

1. **确认起点和恢复状态。** 查看工作树、`origin/ep`、发布历史和已有 draft/tag。
   保留用户的未提交改动；如果本次请求不能确定是否要包含这些改动，先说明。
   上次发布已完成而只缺安装时，只恢复安装，不再分配版本。
2. **确定目标官方基础与版本。** 合并请求使用已核实的官方稳定 tag；本地功能请求
   不顺便升级官方基础。记录 previous、官方 tag/commit、目标版本，运行计算护栏。
3. **修改或合并。** 官方升级保留官方历史和 fork 修改；大冲突先报告。
   尤其检查 API-key/custom-base-URL 兼容、HTTP/SSE 默认、WSL 剪贴板图片、
   MultiAgentV2 默认与 opt-out、Ultra 偏好、上下文显示和 fork 更新渠道等既有行为。
   若官方已提供等价实现，应确认语义后去掉重复补丁，而非机械叠加。
4. **更新版本和最小检查。** 更新 `[workspace.package].version` 及所有继承该版本的
   lockfile 包，包括上游新增包；只改需要变化的版本说明，不全仓替换版本字符串。
   官方升级时同步 Windows 工具的默认官方基线、对应小测试和说明。
   运行 `--check-workspace`；对触及的代码做最小相关检查，遵守用户测试范围。
5. **提交并冻结来源。** 提交到 `ep`（或确认过的升级分支再合回 `ep`），推送
   `origin/ep`。记录最终完整 SHA；两个平台都从这一提交构建，不能继续修改构建来源。
6. **构建、校验、打包。** 使用下述既有入口。任何来源、版本或必需资产校验失败，
   都不能发布。不要把启动了后台构建或取得进程 ID 当成构建成功；等到明确终态。
7. **标记并发布。** 创建 `rust-vVERSION` 的 annotated tag，明确指向最终 SHA；
   检查远端 `ep`、peeled tag 与构建 SHA 一致，再推送该标签。通过 GitHub CLI/API
   建 draft，上传且校验完整资产后，发布为非 prerelease 的 Latest。
   继承的官方 Actions 不等于这个 fork 的发布已完成，不依赖它自动替代本地发布流程。
8. **读回确认。** 核实公开 Release 的 tag、draft/prerelease 状态、Latest、全部资产
   名称/大小/摘要，以及 source commit；不能只凭上传命令成功就结束。
   回报版本、commit、tag、Release 地址和检查范围。用户另外要求安装时，再走真实
   安装器并核验实际命令路径和版本，保留回滚且不泄露配置/认证。

## 既有构建入口和产物

- Windows：按 [ep-windows-build.md](ep-windows-build.md) 使用
  `scripts/ep_windows_release.py build/verify/package`。每步显式传
  `--upstream-ref rust-vX.Y.Z`，必须与目标 fork 的官方基础相同，不能沿用旧默认值。
  使用独立 CRLF checkout 和同基础官方 Windows 参考二进制；数据库验收只用隔离新建
  profile，不改真实数据库或迁移校验逻辑。
- Linux/WSL：从同一提交的 LF 源码构建 `x86_64-unknown-linux-musl`，按上游清单准备
  CLI、code-mode host 及必需 helper，然后调用 `scripts/release-ep.sh`。
  该脚本只是打包器，不会替调用者证明任意预编译二进制的来源；必须保留实际构建 SHA、
  二进制版本/哈希记录，拒绝用旧二进制配新源码的 `SOURCE_COMMIT.txt`。
- 两个平台的版本、嵌入的构建身份及记录都必须匹配最终 SHA。Rust/V8 版本取目标源码
  固定值，不沿用上次构建参数。使用新的输出目录，不混入旧包。
- 默认发布 Windows x86_64 MSVC 和 Linux x86_64 musl，各提供 `.tar.gz`/`.tar.zst`，
  共四个归档；不擅自扩展 macOS、ARM64、签名或可选语音运行时。
- 合并两个平台资产时生成覆盖四个归档的 `codex-package_SHA256SUMS`，不要仅复制
  Linux wrapper 中只覆盖 gzip 的文件；安装器从最终提交的 Git blob 提取，保留 Linux LF。
- Release 同时提供 `install.sh`、`install.ps1`、`SOURCE_COMMIT.txt`、`BUILD_INFO.json`
  和 `VERIFICATION.json`。后两者如实记录版本、来源、平台、摘要、实际检查及未执行项，
  不复制上一版的“通过”结果，不公开个人缓存路径或认证数据。

版本工具不是新的发布器。现有 `.build-tools/` 中的本机恢复脚本可以在核对后复用，
但它们可能带上一次发布的固定版本/路径，不能直接当作通用入口，也不是新 checkout
必须存在的依赖。永久规则在 `AGENTS.md` 和本文件，永久版本护栏在 `scripts/`。

## 中断和失败恢复

在被忽略的本机状态记录中保存目标版本、previous、官方基础、最终 SHA、构建状态、
tag、Release ID、已确认资产及下一步骤，不存 token。恢复前先读回 GitHub 真实状态。

- 草稿上传失败：恢复同一 draft、版本和来源，只补缺失/失败资产，不重复上传已确认项。
- 写操作结果不确定：先对账，不盲目重发创建/发布，不换新版本掩盖失败。
- 已发布版本：只做读回验证或后续安装，不替换资产、不移动标签。
- 源码确实又改变：按已发布历史计算新版本并重新构建；不得给旧二进制改标。
- 权限、凭据、网络或构建阻塞：说明具体未完成步骤，保留恢复信息，不报告完整交付成功。
