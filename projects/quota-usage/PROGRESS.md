# quota-usage 进度

> 接手这个工程先读这里。设计理由在 PROJECT.md，不要重复。

## 当前状态

- 版本：v1.3.1
- 阶段：结构按 skill-generator 规范重建完成，三个功能点可跑，测试 13 项离线 + 2 项联网全绿并已 deploy
- 可用：`python3 scripts/route.py quota` ｜ `checkin` ｜ `list`（加 `--json` 得机器可读）
- 上线工具：`/var/minis/skills/skill-generator/scripts/deploy.py`（工程内不再自建 deploy.py）
- 产物：`mounts/Minis/skills-dist/quota-usage_v1.3.1.zip`
- 已知问题：
  - 麦块云鱼币兑换被平台暂停（`exchange.open=false`），签到得币但换不成额度
  - `minis-config get session.primaryModel` 偶发返回空串，会让供应商识别失败（rc=1）；重跑即恢复，未加重试
- 下一步：无

## 待办

- [ ] 供应商识别偶发失败：`minis-config` 返回空串时给一次重试，或从 `groups` 反查当前组
- [ ] 麦块云免费额度若恢复兑换，重测 `default` 通道的记录行为
- [ ] 七牛活动 2026-11-30 到期后确认额度是否仍可用
- [ ] 麦块云 token 7 天过期，需要时重跑 `scripts/minekuai/login.py --phone`

## 时间线

### 2026-11-24 · v1.3.1
- 新平台接入的收尾步骤改走 skill-generator 的统一部署脚本；`references/dev-workflow.md` 补「提交规范」一节
- 用共享 deploy 上线：同步 3 个文件、推镜像、打包 `quota-usage_v1.3.1.zip`（24 文件 57 KB）
- 顺带把两个仓库里 3 条超 50 字符的历史提交标题改短（只改消息，树哈希比对内容零变化）

### 2026-11-24 · 工程结构对齐 skill-generator v1.8.1
- 工程层不再自建 `WORKFLOW.md` 与 `deploy.py`，上线工具统一用
  `/var/minis/skills/skill-generator/scripts/deploy.py`（含测试、镜像同步、打包归档）
- `.gitignore` 换成规范模板：`/*/` + `!/temp/` + temp 大文件规则
- `PROJECT.md` 目录树与上线链路按实际脚本行为重写
- `normalize.py` 复查：✓ 工程层结构已合规；`validate.py`：0 ERROR 0 WARN

### 2026-11-24 · v1.3.0
- 额度展示改为「付费 / 免费 / 账户」三区，每个池统一「已用 · 剩余 · 总量」三槽位
- 新增按通道（`paygo` / `lite_token` / `default`）聚合的今日与近 3 天消耗
- 测试 15 项全绿（含联网），deploy 完成，三处 24 个文件一致

### 2026-11-24 · v1.2.1
- 功能小节按改写规则补齐四要素（何时用 / 跑什么 / 输出怎么读 / 出错怎么办）
- 测试 12 项全绿，deploy 完成，三处 24 个文件一致

### 2026-11-24 · v1.2.0
- 技能按 skill-generator 规范重建，版本号整体平移到 1.0.0 起算（原 3.x 一一对应顺延）
- 目录定稿：`scripts/route.py` 唯一入口 + `scripts/<平台>/` 子目录 + `references/` 平铺
- 调研结论按规范拆分：接口调研进工程 `docs/`，运行时速查留技能 `references/`
- 仓库历史重写为「一版本一提交」的干净记录