# 妙词元登录态失效 → 重新登录

妙词元**没有验证码登录、没有 OAuth**，只能账号（用户名或邮箱）+ 密码。

## 一条命令

```sh
python3 scripts/miaotoken/quota.py --login '<邮箱或用户名>' '<密码>'
```

成功输出 `✅ 已保存登录态：<用户名>（id <数字>）`。

脚本会：
1. `POST /api/user/login` 换 `new_api_refresh` cookie（30 天有效）
2. 立刻用该 cookie `POST /api/user/auth/refresh` 验证可用
3. 只把 `refresh` 与 `user_id` 写入 `config.json`（0600），**不保存密码**

## 什么时候需要重来

| 提示 | 原因 |
|---|---|
| `AUTH_SESSION_REVOKED` / `401 Unauthorized` | refresh cookie 被用掉了且没保存新值，或 30 天到期 |
| `AUTH_ORIGIN_FORBIDDEN` | 刷新时缺 `Origin` 头（脚本已带，除非手动改） |
| `HTTP 429 限流` | 连续登录过密，等 90 秒 |

## 为什么不用 API Key

`GET /api/usage/token/` 用 `sk-...` 只能查该 Key 自身的额度，拿不到账号总额、其它 Key、调用日志。
账号级数据必须走登录。

## 注意

- 密码会出现在命令历史里，登录完可清 shell 历史，或改用 `MT_PASS` 环境变量先 `read` 进来再传
- 同一账号重复登录会触发 429，日常查询不需要重新登录——脚本每次用 refresh 换访问令牌