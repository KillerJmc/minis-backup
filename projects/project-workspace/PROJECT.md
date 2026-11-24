# project-workspace 技能：做过什么

工程 = `<挂载>/projects/<会话分组名>` 下的一个目录。这个文件记录本技能的设计决定与改动，方便接手的人不用翻会话。

## 功能点（用户能触发的四件事）

| 功能 | 触发关键字 | 作用 |
|---|---|---|
| 项目绑定 | 开场自动、切到 X 工程、新建项目 | 让本会话绑定到某个工程目录 |
| 项目迁移 | 项目改名、合并工程、把 A 并到 B | 旧工程复制到新工程 |
| 项目查询 | 有哪些项目、我在哪个项目 | 工程清单、当前工程路径 |
| 资源同步 | 同步技能、同步记忆 | app 内与外部镜像双向补齐 |

## 关键决定（都是踩过坑改的）

- **迁移只复制，永不删除旧工程**：一个分组下有多个会话，别的会话可能还指着旧目录。旧目录留给用户确认后手动清理。
- **同名即中止**：目标侧存在同一相对路径（文件或目录，不看内容）就 `rc=1`，两边一个文件都不动。曾经实现过"内容相同就跳过"，结果跳过后删了旧目录，等于替用户做了数据决策。
- **改名不让用户提供名字**：App 改了分组名，脚本用 `minis-sessions-cli status` 读当前分组当新名，旧名来自 `.project-prev` / `.project`。用户在对话里说一句"我改项目名了"，直接跑 `ws.py migrate`。
- **同组多会话切换不误报**：旧工程文件都已在目标工程里 → 判定别的会话迁移过，`auto` 直接切到新名，不提示跑迁移（那条命令必然冲突）。
- **目录输出用完整相对路径**，不靠缩进：`666/ · 1 项`、`666/h.exe · 18.5 MB`。缩进经过 UI 渲染会被吃掉，层级就丢了。
- **未知 flag 不许当工程名**：`migrate --json` 曾把工程改名成 `--json` 并删掉原目录。现在名字以 `-` 开头一律 `rc=2`。
- **工程里不建模板文件**：没有 PROJECT.md/index 自动生成，目录内容本身就是上下文。

## 测试

`tests/cases.json` 里 146 条**对话级**用例：每轮写用户原话 → 该跑的 command → 退出码/输出/复述 → 结束后对磁盘下结论。

```sh
cd /var/minis/skills/project-workspace && python3 tests/run.py   # 末行须为 失败 0 项
```

覆盖 A–H 功能组 + R1–R13 风险轮；改代码必须补用例、跑绿才 `sync --push`。

## 目录

```
/var/minis/skills/project-workspace/
├── SKILL.md              功能表 + 各功能做法 + 修改门禁
├── references/commands.md 参数、退出码、JSON 结构
├── scripts/ws.py         唯一入口
└── tests/{cases.json, run.py, README.md}
```

流程见 `/var/minis/skills/skill-generator/references/git-workflow.md`，部署用 `/var/minis/skills/skill-generator/scripts/deploy.py`（在工程目录下执行）。

## 遗留

- 反复改名会累积旧工程目录；`list` 尚未标出"内容被其他工程完全包含"的历史残留。
- 端到端"模型转述是否正确"只能靠真实会话验证，脚本层只能保证输出本身不含歧义。

## 2026-11-16 · 引入 git 与上线门禁

- 技能改为在 `<挂载>/projects/Project Skill/project-workspace/` 工作副本上修改，git 记录历史；不再直接覆盖写 `/var/minis/skills/`。
- 部署由 skill-generator 的共享脚本负责：跑测试 → 同步 skills → 推外部镜像 → 打包。
- 流程规范统一放在 skill-generator 的 `references/git-workflow.md`。
