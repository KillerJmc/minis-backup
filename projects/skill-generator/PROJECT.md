# skill-generator 工程

App 分组 `skill-generator` 对应本目录。本工程管一件事：**技能的创建、改写与结构校验**——
从功能点出发生成技能骨架，按判据重排现有技能，静态检查并列出问题。

## 承载什么

| 内容 | 位置 | 版本 |
|---|---|---|
| 技能工作副本 | `skill-generator/` | v1.3.1 |
| 工程记录 | 本文件 + `PROGRESS.md` | — |
| 上线工具 | `/var/minis/skills/skill-generator/scripts/deploy.py` | — |
| 临时数据 | `temp/` | 进工程 git |

## 关键决定

- **两层目录**：外层工程层只放工程文件（本文件、`PROGRESS.md`、`temp/`、`docs/`），内层 `skill-generator/` 才是完整技能。部署脚本只扫描含 `SKILL.md` 的子目录，工程文件永远不会混进部署产物。
- **工作副本从部署产物取**：2026-11-23 建本工程时，`/var/minis/skills/skill-generator/`（v1.2.0）已经是当时最新版，直接 `cp -a` 作为工作副本起点，之后才在副本上继续改。这样不必再从别的工程搬历史。
- **`temp/` 进工程 git**：留下「试过什么、抓到了什么」的痕迹，只挡大文件（图片/PDF/压缩包/数据库），提交走 `chore(tmp): …`。
- **`docs/` 是沉淀层**：只收接口调研、外部规范摘录、长设计说明、排障记录、历史开发日志；必须在下方「目录」里挂引用。进度流水归 `PROGRESS.md`，一句话决策归本文件。
- **本技能只管 Minis 落地**：`skill-creator` 是通用 Anthropic 规范（App 里 `/var/minis/skills/skill-creator/`），本技能不覆盖它，只补 App 显示、触发、iSH 环境相关的规定。

## 目录

```
projects/skill-generator/           ← 工程层（本目录）
├── PROJECT.md                      本文件：是什么、为什么这样设计
├── PROGRESS.md                     做到哪、下一步
├── .gitignore                      排除 /skill-generator/、大文件、缓存
├── temp/                           临时数据、中间稿（进工程 git）
└── skill-generator/                ← 技能层（完整技能，独立 git 仓库）
    ├── SKILL.md                    v1.3.1：功能表 + 各功能做法 + 执行约束
    ├── references/
    │   ├── checklist.md            上线前逐项清单（9 节）
    │   ├── layout.md               两层目录、docs 收录标准、PROJECT/PROGRESS 模板
    │   ├── git-workflow.md         双仓库、deploy 必备行为、坑
    │   └── patterns.md             好/坏写法对照
    ├── scripts/validate.py         结构校验器（ERROR / WARN 两档）
    └── tests/                      离线回归 23 项，覆盖 valid/meta/body/env/layout 五组
```

## 文档分层

| 内容 | 去哪 |
|---|---|
| 是什么、为什么这样设计 | 本文件 |
| 做到哪、下一步 | `PROGRESS.md` |
| 调研结论、长文档 | `docs/<主题>-<类型>.md`，必须在本文件「目录」里被引用 |
| 运行时参数、退出码、规则细节 | `skill-generator/references/`（会被加载进上下文） |
| 抓到的原始响应、草稿 | `temp/`（入库记变动，大文件挡掉） |

## 上线链路

```
skill-generator/（技能仓库：改 → 测 → commit）
      ↓ 共享 deploy.py（测绿才走）
/var/minis/skills/skill-generator/            （App 权威源）
      ↓ ws.py sync --push
/var/minis/mounts/Minis/skills/skill-generator/（外部镜像）
```

## 遗留

- 校验器只覆盖结构，不检查「`description` 是否真的能被用户说出口」这类语义问题——那需要真实会话验证。
- `skill-creator`（Anthropic 通用规范）与本技能的分工写在这里和 SKILL.md 的执行约束里，但没有各自独立的说明文档。