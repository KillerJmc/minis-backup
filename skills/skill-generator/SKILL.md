---
name: skill-generator
description: 新建技能，改写技能，校验技能结构
version: 1.8.3
triggers: 写技能,新建技能,改技能,技能规范,校验技能

---

新建技能，改写技能，校验技能结构。

## 功能

用户能主动触发的操作。前四件是功能，后四件会动文件或线上，必须用户亲口说：

| 功能 | 触发关键字 | 作用 |
|---|---|---|
| 技能新建 | 写个技能、新建技能、做个技能 | 从功能点出发生成可运行的技能骨架 |
| 技能规范 | 改规范、规范化工程、整理工程 | 把已有工程整理成规范结构 |
| 技能改写 | 改技能、重构、可读性差 | 按判据重排现有技能，不改变行为 |
| 结构校验 | 校验技能、检查技能规范 | 静态检查并列出问题清单 |
| 改动授权 | 改吧、开始改、动手 | 只改工作副本：内容、版本号、变更记录、用例；不提交、不发布 |
| 发布 | 发布、部署、上线 | 先贴本次变更记录，认可后才测试、提交、部署、打包 |
| 打包产物 | 出个包、打包、生成 zip | 只打包不上线：`scripts/deploy.py --pack-only`，源取挂载镜像 |
| 撤销 | 撤销、回滚 | 提交退回上一版、线上退回上一版，改动全保留 |
| 丢弃修改 | 丢弃修改、不要了 | 删除未提交改动，执行前先列清单 |

## 技能新建

先问清三件事，再动笔：

1. **功能点**：用户能主动说出口的几件事（通常 2–5 个）；
2. **触发关键字**：用户会怎么称呼这些事，用他的话，不用技术词；
3. **数据放哪、命令怎么跑**：至少要能用一个命令复现核心动作。

生成两层：外层是工程层（项目文档、上线脚本、临时目录），内层是完整技能目录。
工程层必须建 `PROJECT.md`、`PROGRESS.md`、`.gitignore`、`temp/`、`docs/`；技能层的 `assets/` 是可选目录，用到才建。
没有内容的目录放 `.gitkeep` 占位，不要预建空目录——「以后再说」的项目最后都成了空缺。

目录树不复述：`normalize.py --apply` 建出来就是标准结构；两层同名即可（`a-new-skill/a-new-skill/`），
工程文件在外层，只有含 `SKILL.md` 的子目录才会被部署。

`PROJECT.md` / `PROGRESS.md` 的模板与更新规则见 [`references/layout.md`](references/layout.md)。

`SKILL.md` 的头部与首句：

```markdown
---
name: a-new-skill
description: 功能一，功能二，功能三
version: 1.0.0
triggers: 触发词一,触发词二,触发词三
---

功能一，功能二，功能三。
（这一行必须与 description 逐字一致：Minis 的技能详情页显示的是这句，不是字段）
```


## 技能规范

把已有工程整理成规范结构。**先查名字，再补文件**；名字不对就停。

```sh
python3 /var/minis/skills/skill-generator/scripts/normalize.py          # 预演
python3 /var/minis/skills/skill-generator/scripts/normalize.py --apply  # 执行
```

三步，**第一步只读**：

1. **查名字**——工程目录名对 App 分组名、技能目录名对 `name`。不一致只输出该改成什么，退出码 `3`，一个文件都不动。
   改名要迁移目录，是用户的决定；脚本替他改，别的会话绑定会瞬间失效。
2. **等用户迁移**——用户改分组名、跑 `ws.py migrate`，回来说一声再重跑。
3. **改造工程层**——补 `PROJECT.md`、`PROGRESS.md`、`.gitignore`，`.tmp` 改 `temp`，缺变更记录就生成一条，`docs` 未被引用则报告。

边界：不动技能目录内容、不搬目录、不删文件、不自动 commit，其他工程一律不碰。

检查项、报告格式与退出码见 [`references/normalize.md`](references/normalize.md)。

## 技能改写

按这四条改，顺序别乱：

| 步骤 | 做什么 | 常见毛病 |
|---|---|---|
| 1 | 只留用户能触发的功能点 | 把内部准备步骤（建目录）、约束（写文件落点）当功能 |
| 2 | 功能名改成概括性动宾 | 用口语当名字（「我在哪」「改名、合并」） |
| 3 | 每个功能写「何时用 → 命令 → 输出怎么读 → 出错怎么办」 | 只写命令，不写输出语义 |
| 4 | 参数、退出码、边界下沉 `references/` | 正文堆细节，一屏看不完 |

改完跑一次结构校验：

```sh
python3 /var/minis/skills/skill-generator/scripts/validate.py <技能目录>
```

改前改后的具体写法对照见 [`references/patterns.md`](references/patterns.md)。

## 结构校验

```sh
python3 /var/minis/skills/skill-generator/scripts/validate.py <技能目录> [--json] [--allow-dirty]
```

输出 ERROR 与 WARN：ERROR 必修、WARN 看情况。退出码 `0` 无 ERROR、`1` 有 ERROR、`2` 用法错误。
`--allow-dirty` 只在发布流程里用（那时工作区必然有未提交改动）。

**工具判定的部分**（不用人看）：元数据完整性、首句与 `description` 一致、功能表存在且不含参数编号、
每个功能小节有代码块、正文体量、references 指向、tests 存在、变更记录格式与版本一致、
工程层文件齐全、部署产物纯净（无 `.git`/`.gitignore`）、是否在 git 仓库、忽略规则。

**工具判定不了的部分**：见 [`references/checklist.md`](references/checklist.md)，那是给人看的。

## 规范要点

工具能判的都交给了 `validate.py`（元数据、首句一致、功能表、正文体量、references 指向、tests 存在、
变更记录格式、工程层文件、git 状态、忽略规则、部署产物纯净度）。这里只留**判定不了**的：

| 层 | 规则 |
|---|---|
| 正文首句 | 与 `description` 一致，因为它显示在 App 描述栏，不是字段本身 |
| `assets/` | 只在脚本真要读模板/图标/字体时才建，首次生成不建 |
| 文档分层 | 决策进 `PROJECT.md`，进度进 `PROGRESS.md`，调研进 `docs/`，运行时参数进 `references/` |
| 测试与校验时机 | 修改阶段只写用例、不跑；发布前统一跑 |
| `tests/` 写法 | 数据驱动或直接在 `run.py` 里断言都行；硬要求是末行「失败 0 项」且能离线复跑 |

写法对照见 [`references/patterns.md`](references/patterns.md)；目录布局与文档模板见
[`references/layout.md`](references/layout.md)；仓库与提交流程见 [`references/git-workflow.md`](references/git-workflow.md)；
工具判定不了的清单见 [`references/checklist.md`](references/checklist.md)。

## 版本与上线

发布分两轮，但**顺序和校验由 `release.py` 保证**，不靠记忆：

```sh
python3 /var/minis/skills/skill-generator/scripts/release.py status
python3 .../release.py prepare <技能名>     # 生成确认包与 snapshot
python3 .../release.py confirm <snapshot>   # 用户确认后执行
```

**第一轮**：`prepare` 输出变更记录条目 + 文件清单 + 增删行数 + snapshot。
把这段原样贴到对话正文里，然后**结束这一轮**。

「发布吧」「可以发了」只表示可以开始流程，**不等于认可条目**——要等用户对条目点头。

**第二轮**：`confirm` 重算 snapshot 与传入值比对：

| 情况 | 结果 |
|---|---|
| 一致 | 依次 validate → 跑测试 → commit → deploy → 打包，最后打印版本、产物、归档 |
| 不一致 | 拒绝并给出新旧 hash，提示重新 prepare（退出码 3） |
| 校验或测试不过 | 拒绝上线 |

**贴出后改了任何文件，snapshot 就变，`confirm` 直接拦下**——这是把「确认的生效条件」从文字变成代码。

snapshot 不是授权凭据（重新 prepare 会拿到新 hash），它保证的是：**用户看到的那份清单**与**即将提交的内容**是同一份。

**发布后必须汇报四样**：commit hash 与 message、deploy 推送的文件与镜像结果、产物 zip、三处版本号。
不能只说「已发布」。

## 撤销与回滚

```sh
python3 /var/minis/skills/skill-generator/scripts/release.py restore
```

它只打印六步命令，**不自动执行**——撤销自动化出错代价高于手打。

语义要记住的两条：

- 撤销与回滚是**同一件事**：提交退回上一版、线上退回上一版，**改动全部保留**。
- 唯一会丢文件的是**丢弃修改**，只有用户明确说才做，且执行前先列清单。

禁止 `git reset --hard`、`git checkout -- .`、`git revert` 代替撤销、直接删线上目录——这些都会丢改动或丢旧版。

## 执行约束

- **技能改动由用户授权**：只有用户明确表示要改（例如「改」「开始改」「按这个改」「动手」）时才修改技能目录里的文件；讨论、提问、给方案、对比写法时只输出文字。关键词只是例子，判断看语义，拿不准就问。
- **工程层不需要授权**：`PROJECT.md`、`PROGRESS.md`、`docs/`、`temp/` 属于记录，随做随记，改完直接提交。
- **修改阶段只改文件 + 允许自测**：授权「改」之后编辑工作副本——内容、`version`、`CHANGELOG.md` 条目，**连同测试用例一起写**；可以跑**自测**（见下），但**不跑 `tests/run.py`、不跑 `validate.py`、不 commit、不 deploy**。
- **测试写在这时、跑在发布时**：用例随改动一起写，避免提交时忘了补；但跑测试与校验是发布那一步的事，修改阶段跑了会让人误以为已经验证过。
- **三件事别混**：

| 类别 | 是什么 | 修改阶段 |
|---|---|---|
| 语法检查 | 只解析不执行，如 `py_compile` | 可以跑 |
| **自测** | 在 `/tmp` 沙箱造输入，验证刚写的代码是否按预期工作 | **可以跑，但必须逐条报告** |
| 测试 | 跑技能自带回归集（`tests/run.py`）、校验真实技能（`validate.py`） | 不要跑，留给发布阶段 |

- **自测必须报告**：凡是修改阶段跑过的命令，在回复里逐条列出命令与结论，不能默不作声。没报告就等于没跑——事后无从核对。
- **新建/规范后验收**：技能新建、技能规范完成后各跑一次 `validate.py`，确认生成物结构合规；这是产出物验收，不是日常修改。
- **commit 与发布一起做**：用户说发布时，先确认变更记录，认可后才 commit 并 deploy；不认可就继续改。修改与提交、上线三者不在同一时刻。
- **讨论产出统一落 `temp/`**：未获授权前，方案、草稿、调研、对比写法一律写成工程层 `temp/` 里的文件，不写技能目录、不写 `/var/minis/workspace/`、不写 `/var/minis/shared/`。
- **达标才沉淀 `docs/`**：满足收录标准的，才从 `temp/` 重写成 `docs/<主题>-<类型>.md` 并在 `PROJECT.md` 挂引用；其余留在 `temp/`，用完即删。
- **两层目录**：外层工程层只放 `PROJECT.md`、`PROGRESS.md`、`temp/`、`docs/`；内层技能目录放技能本体。工程里**不建 `WORKFLOW.md`、不放 `deploy.py` 副本**——流程见本技能 `references/git-workflow.md`，工具用 `scripts/deploy.py`（在工程目录下执行，或 `--project` 指定）。
- **生成技能时创建 `PROJECT.md` 与 `PROGRESS.md` 骨架**，写在工程层：前者答"为什么这样设计"，后者答"现在到哪、下一步"，两个文件都必须随工程推进维护。
- **`temp/` 进外层 git**（不在 `.gitignore` 里），用来留下「试过什么、抓到了什么」的痕迹；大文件用 `.gitignore` 挡掉，提交用 `chore(temp): …`。
- **不覆盖 `skill-creator`**：它是通用 Anthropic 规范，本技能只管 Minis 落地（App 显示、触发、iSH 环境）。
- 校验只报问题，**不自动改写文件**；改动交给用户确认。
