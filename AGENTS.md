# EP fork 项目指令

本仓库是 `Epresin/codex`，维护分支为 `ep`；`origin` 是我们的 GitHub fork，
`upstream` 是官方 `openai/codex`。不要向 upstream 推送。发布操作细则见
[docs/ep-release-workflow.md](docs/ep-release-workflow.md)，Windows 构建约束见
[docs/ep-windows-build.md](docs/ep-windows-build.md)。

## 默认完成标准

- 用户要求实现功能、修复问题或合并官方版本时，默认交付完整版本：修改、必要检查、
  升版本、提交、推送 `origin/ep`、构建 Windows 和 Linux/WSL 包、推送标签、
  发布 GitHub Release、验证发布结果。不要停在“源码已改”“已提交”或“已推送”。
- 不需要用户逐步重复说“提交、推送、发布”。用户明确说“只改代码”“先别发布”
  或限制检查范围时，服从该次要求。纯提问、调研、方案或发布规则讨论不自动触发发布。
- 沿用项目既有发布方式，不擅自引入大规模 CI 或重写发布系统。
- 本机安装是独立步骤；用户要求升级本机时再执行，并分别报告 Windows/WSL 实际安装结果。
  发布成功不等于本机已升级。

## 版本号硬规则

正式 fork 版本为 `X.Y.Z-epr.N`，标签为 `rust-vX.Y.Z-epr.N`，`N >= 1`。
**N 是某个官方基础版本内的修订号，不是跨官方版本累计的计数器。**

- 同一官方基础：`0.164.0-epr.2 -> 0.164.0-epr.3`。
- 升级官方基础且该基础首次发布：`0.164.0-epr.3 -> 0.165.0-epr.1`。
- 上述升级绝不能变成 `0.165.0-epr.3` 或 `0.165.0-epr.4`。
- 官方补丁号变化也算基础改变，例如 `0.164.0-epr.3 -> 0.164.1-epr.1`。
- 旧 `-ep.N` 仅作为历史输入兼容；新发布一律用 `-epr.N`。
- 先核实 GitHub 已发布的 fork 版本、目标基础已有发布及同名 tag/draft，再确定编号。
  不以已改过的 Cargo 版本或 `git describe` 最近的官方 tag 充当“上一发布版”。
- 失败重试/恢复 draft 沿用原版本、tag、commit 和 Release ID，不再递增编号。
  已发布版本不可重标、移 tag 或替换资产；新代码必须发新版本。

发布前必须运行版本护栏，参数来自核实后的发布历史和官方稳定 tag：

```sh
python scripts/ep_release_version.py --previous PREVIOUS_FORK_VERSION --upstream OFFICIAL_TAG
python scripts/ep_release_version.py --previous PREVIOUS_FORK_VERSION --upstream OFFICIAL_TAG --check-workspace
```

命令失败就停止发布并修正版本；不要绕过校验。该工具不查询远端，远端历史和重试状态
仍须按发布细则核实。`--check-workspace` 通过不代表 Cargo.lock、二进制或发布资产已验证。

## 合并与构建边界

- 指定官方版本就合并那个版本；“最新”必须先查询官方稳定发布，不能凭记忆猜。
- 保留个人修改；遇到大冲突、语义冲突、数据迁移风险或个人功能取舍，先说明问题。
  不允许用整仓覆盖、强制重置或静默丢弃 fork 功能来消除冲突。
- 同步 workspace 版本与继承该版本的 Cargo.lock 包，避免遗漏新加入的 workspace 包；
  不借此无关升级第三方依赖。官方基线、Windows 工具默认基线及相关说明必须一致。
- 两个平台必须来自同一最终提交，二进制版本、tag、SOURCE_COMMIT 和构建记录须一致。
  不拿旧二进制改文件名/清单版本冒充新构建。
- Windows 使用独立 CRLF checkout；Linux/WSL 保持 LF。遵守 Windows 构建文档，
  不修改原工作区换行配置，不改 SQL、迁移 checksum 或绕过数据库校验。
- 仅运行改动相关的最小必要检查；不默认跑全量测试或无关手工验收。
  不用“少测试”跳过真实构建、版本/提交身份和发布资产完整性校验。
- 不读取/修改真实用户数据库来做测试，不将认证、配置、缓存、日志、二进制或个人路径提交。
  `.build-tools/` 和 `dist/` 保持忽略；通用流程规则和护栏保存在受版本控制的文件中。

## 交付回报

报告版本号、提交、tag、Release 地址、Windows/Linux 资产是否齐全及必要检查结果。
失败或权限/网络阻塞要明确指出未完成步骤并保留可恢复状态，不能把部分成功说成发布完成。
