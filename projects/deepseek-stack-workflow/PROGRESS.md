# PROGRESS

## Goal

一个技能承载 deepseek-stack 的 29 个原技能：`SKILL.md` 只做壳（可见提示 + 路由 + 常开 + 调用 + 收尾），
原文一字不改放在 `references/ds-*.md`。
验收：`validate.py` 0 ERROR、`tests/run.py` 失败 0 项、29 份原文 md5 与上游一致。

## 当前状态

**v1.0.0 已改完，未发布。** 改动留在工作副本里（未 commit），等用户亲口说发布。

| 项 | 结果 |
|---|---|
| validate.py | 0 ERROR，0 WARN |
| tests/run.py | 共 9 项，失败 0 项 |
| 原文一致性 | 29 份 md5 对上 `tests/manifest.json`（上游 `d4f1ebe`） |
| 部署 | **无**。此前那次误发布已撤回 |

## Done

- 恢复 29 份上游原文，按原名放进 `references/`，逐字节未改。
- `SKILL.md` 重写为壳：不再内联路由表（路由表只在 `references/ds-help.md`），不再复制任何技能步骤。
- 新增「可见提示」规范：`▶ 调用 ds-xxx`、`▶ 路由到 ds-xxx`、`▶ 改路由：A → B，原因`。
- `tests/run.py` 扩到 9 项：原文 md5 比对、壳不内联路由表、壳不替 ds-help 做路由判断。
- 修掉壳里越界：删掉所有具体路由映射与带技能名的样板，壳只留 `ds-help`、`ds-mode` 两个名字。
- 撤回误发布：删 `/var/minis/skills/deepseek-stack-workflow`、外部镜像同名目录、`skills-dist` 里的 zip。
- 按用户要求删除 9 个独立 `ds-*`（App 目录与镜像两处），现在 `ds-*` 只存在于本技能的 `references/` 里。

## Next

1. 等用户验收 v1.0.0 的内容，说发布后才走 `release.py prepare`。
2. 发布后 Rescan，确认新技能出现在 Skills 页。
3. ~~决定 9 个 ds-* 去留~~ —— 已删，只保留 references/ 里的原文。

## Open questions

- 9 个 `ds-*` 独立技能去留：留着 = 可单独触发、但占 20 个展示名额；删掉 = 只能经路由间接用。

## Key facts

- 上游 `aicodeking/deepseek-stack`@`d4f1ebe`，全仓 29 个技能，唯一脚本 `ds-watch-pr/scripts/watch_pr.py`（只读 `gh pr view`）。
- `validate.py`：frontmatter 四字段齐全、name 等于目录名、CHANGELOG 最新版本行等于 version、正文首句等于 description、必须有 `## 功能`、正文 ≤500 行、技能目录在 git 仓库里。
- `## 功能` 表第一列会被匹配同名 `## 小节`，小节里没代码块报 WARN。
- `release.py prepare` 要求有未提交改动；已提交的工程它跑不动。
- **发布必须用户亲口说**。改完就 deploy 是违规，用户当场指出过。
- shell_execute 命令超 1000 字符会被截断且静默失败，长内容用 file_write。
