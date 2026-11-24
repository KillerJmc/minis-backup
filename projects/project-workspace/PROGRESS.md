# skill-generator / project-workspace 进度

> 接手这个工程先读这里。设计理由在 `PROJECT.md`，不要重复。

## 当前状态

- skill-generator：v1.8.3（2026-11-24，`release.py` 发布流程 + 打包归档）
- project-workspace：v1.5.1，工程只需 `.git` + `PROGRESS.md`，产物全写工程目录
- 阶段：两个技能都可上线，测试全绿（workspace 156 项）
- 已知问题：无
- 下一步：把 skill-generator 的新流程用到其他技能工程上

## 待办

- [x] ~~工程层 `.gitignore` 的 `/*/` 会把 `docs/` 一并忽略~~：v1.8.3 已把模板改为只排除 `/<技能名>/`，实测 `docs/` 不再被忽略
- [x] ~~project-workspace 增加 PROGRESS.md 的约定~~：v1.5.0 起工程必备就是 `.git` + `PROGRESS.md`
- [ ] skill-creator 工程（另一个工程）按新规范统一后，把它的经验回流到本技能的 layout.md

## 时间线

### 2026-11-24 · project-workspace v1.5.1 · 对齐最新规范
- 「修改本技能后」改用 `release.py prepare` → `confirm <snapshot>`；删掉已不存在的 `WORKFLOW.md` 引用与手敲 `deploy.py` 的旧步骤。
- 澄清分层：普通工程 `.git` + `PROGRESS.md` 两项；技能工程另按 skill-generator 补齐 `PROJECT.md`、`.gitignore`、`temp/`、`docs/`。
- 发布：提交 `efbd21a`，产物 `project-workspace_v1.5.1.zip`（7 文件 32 KB），归档旧版 v1.5.0。

### 2026-11-24 · project-workspace v1.5.0 · 工程结构收敛为两项
- 工程目录必备收敛为 `.git` + `PROGRESS.md`，其余骨架一律不建；设计理由并进 `PROGRESS.md`。
- 会话产物全部写进工程目录，不往 `/tmp`、`workspace/`、`shared/` 放；测试沙盒除外。
- 工程层改为用 skill-generator 的 `normalize.py` / `validate.py` / `scripts/deploy.py`，不再自建 `WORKFLOW.md` 与 `deploy.py`。
- `.gitignore` 按规范补 9 行标准规则；产物 `skills-dist/project-workspace_v1.5.0.zip`（8 文件，32 KB）。

### 2026-11-24 · project-workspace v1.4.1 · 补变更记录并重编版本号
- 按 skill-generator 规范补 `CHANGELOG.md`，从早期会话还原 1.0.0→1.4.1 十条历史。
- 版本号整体重编：6.4.0 系列压到 1.4.x，行为变化升 minor、纯文档升级 patch；`SKILL.md` version 同步为 1.4.1。
- 全量测试首跑 3 项失败（R7 组执行异常），清 `/tmp/ws-test/e2e` 后 156 项全绿——沙箱残留会干扰。

### 2026-11-23 · skill-generator v1.2.0 · docs 与 .tmp 定规
- `docs/` 定为沉淀层：接口调研、外部规范摘录、长文档、排障记录；末行三行写结论，必须在 `PROJECT.md` 里被引用。
- `.tmp/` 改为进工程 git（记录试过什么），只挡图片/PDF/压缩包/数据库等大文件，提交用 `chore(tmp): …`。
- `validate.py`：新增 docs 未引用告警（P5/P6）；`.git` 告警只在「上层不是工程层」时报，工作副本不再误报（P7）。
- 测试 20 → 23 项。

### 2026-11-23 · skill-generator v1.1.0
- 明确两层目录：外层工程层（PROJECT.md / PROGRESS.md / WORKFLOW.md / deploy.py / .tmp / docs），内层技能目录只放技能本体。
- 新增 `references/layout.md`：目录树、各文件职责、临时文件落点、PROJECT.md 与 PROGRESS.md 模板与更新规则、多 chat 并发处理。
- `validate.py` 新增工程层检查（P1–P4 四条用例）：工程层缺 PROJECT.md / PROGRESS.md、技能目录误放工程文件时告警。
- 删除「生成技能时不自动创建 PROJECT.md」的旧表述，改为「在工程层创建 PROJECT.md 与 PROGRESS.md 骨架」。
- 测试 16 → 20 项。