# 奇瑞汽车App 每日积分自动化

每天自动：签到 → 分享帖子×2领奖 → 发视频帖×2（资讯混剪，OSS直传+发布）→ 查积分打卡。

> 状态：**已跑通**（2026-09-18 本地验证：签到OK、分享2/2、发视频发布+删除OK，积分2425→2428）。

## 1. 每天能拿多少分（按任务中心规则）

| 任务 | 规则 | 状态 |
|---|---|---|
| 连续签到 | eventCode SJ10002 | ✅ 已验证 |
| 分享帖子 | +1/次，上限2分/天，领奖 SJ10003 | ✅ 已验证（2425→2427） |
| 发视频帖 | +10/条，上限20分/天 | ✅ 发布链路已验证（发完删帖也算完成，任务变done=4） |
| 发表优质帖/帖子加精/被推荐/评论加精/客户之声 | +20~+500 | ⚠️ 需官方人工审核，机器保证每天去发 |

## 2. 仓库结构

```
src/daily.py         # 每日任务主入口（短信登录/token + 签到/分享/发视频/查分）
src/video_maker.py   # 资讯混剪：videos/raw 素材 → 每天2条竖屏成品
src/chery_client.py / src/tasks.py  # 旧框架（已由 daily.py 取代，留档）
videos/raw/          # 放2~3段奇瑞相关素材（横/竖屏都行）
videos/out/          # 每天生成的成品（git忽略，由 CI 生成）
.github/workflows/daily.yml  # 每天北京时间08:00自动跑
```

关键接口（mobile-consumer-sapp.chery.cn，query `access_token+terminal=3` AES加密，body `{"data":加密JSON}`）：
- 登录：`POST uaa2c /api/v1/uaa/mobile/mobile-code-login {mobile, verificationCode}`
- 签到：`POST /web/event/trigger {eventCode:SJ10002}`
- 分享：`POST /web/community/contents/{id}/share` + 领奖 `{eventCode:SJ10003}`
- 发视频：STS签名 → OSS直传 → `POST /web/community/contents {contentType:3, video:{url,duration,cover}}`
- 查分：`GET /web/user/current/details?access_token=&terminal=3`（明文）

借鉴：旧仓库 `jiuzihe36/chery/chery_sign.py` 的 APP_HEADERS（Dart UA + terminal=3 + event/trigger）是打通签到/分享的关键。

## 3. 维护（只需做一次）

- `CHERY_TOKEN` 已存进仓库 Secrets（Actions 可用）。token 有效期约2年，到期后跑一遍
  `send_sms → login_by_sms`（daily.py 里有函数）换新 token 再存一次。
- 加素材：往 `videos/raw/` 扔奇瑞相关视频即可，CI 每天混剪2条。
- 手动跑一次：仓库页 `Actions → 每日积分任务 → Run workflow`。

## 4. 安全提醒

- 私有仓库，不要公开。
- 混剪素材请用官方活动/自己实拍或已授权素材，避免纯搬运被判违规。
- token 轮换后去 https://github.com/settings/tokens 删掉旧 `ghp_`。
