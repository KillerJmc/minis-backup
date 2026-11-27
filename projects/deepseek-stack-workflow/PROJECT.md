# deepseek-stack-workflow

## 是什么

一个技能，壳 + 29 份原文。壳是 `SKILL.md`（只做路由与调用规范），原文是 `references/ds-*.md`
（`aicodeking/deepseek-stack` 的 29 个 `SKILL.md`，一字未改，文件名与上游目录同名）。

- 上游：https://github.com/aicodeking/deepseek-stack（MIT，346★），快照 `d4f1ebe`（2026-10-28）
- 本工程：`/var/minis/mounts/Minis/projects/deepseek-stack-workflow/`，技能主体在 `deepseek-stack-workflow/`（独立 git）

## 为什么这样设计

用户要的是「原文不动 + ds-help 路由」，所以壳里不含任何路由判断：它只规定先读 `ds-help.md`、按规定格式把路由显示给用户。例子会被 agent 当成规则，所以壳里连一个具体技能名都不许出现——`tests/run.py` 有一条专门拦这个。

## 目录

```
deepseek-stack-workflow/          工程层（本仓库）
├── PROJECT.md                    本文件
├── PROGRESS.md                   做到哪、下一步
├── .gitignore                    只排除技能目录
├── temp/                         中间稿
└── deepseek-stack-workflow/      技能主体（独立 git 仓库）
    ├── SKILL.md                  壳：可见提示 + 路由 + 常开 + 调用 + 收尾
    ├── CHANGELOG.md
    ├── references/ds-*.md        29 份上游原文，逐字节未改
    ├── scripts/watch_pr.py       上游 ds-watch-pr 的只读轮询器
    └── tests/
        ├── run.py                8 项冒烟检查
        └── manifest.json         29 份原文的 md5（防止被悄悄改写）
```

## 上线链路

改完在**工程目录**跑 `release.py prepare deepseek-stack-workflow`，把确认包贴给用户；
用户认可后 `confirm <snapshot>`：校验 → 测试 → 提交 → 部署到 `/var/minis/skills/` → 打包。
用户没亲口说发布之前，不 commit、不 deploy。
不要在 `/var/minis/skills/` 下直接改，那是部署产物。

## 遗留

- v1.0.0 曾被误发布（未经授权跑了 `deploy.py`），线上与镜像已删除，产物 zip 已删。
- `skills/` 目录是 1.0.0 时期装 9 个 `ds-*` 的旧快照，仅作历史；权威原文在 `references/`。
- 上游仍在演进，没有自动更新通道；升级要重拉上游、比对 `tests/manifest.json`。
