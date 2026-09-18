# 奇瑞汽车App 每日积分自动化

每天自动（北京时间 08:00）：
  下载 B站「奇瑞瑞虎8改装」视频 → 混剪 2 条竖屏 → 签到 → 分享×2 →
  搬运发视频×2（从社区扒别人视频→二次剪辑→OSS直传→发布，不删除）→ 查积分打卡。

> 状态：**已跑通**（2026-09-18 本地验证：签到OK、分享2/2、搬运发视频发布成功1条）。

## 1. 每天能拿多少分（按任务中心规则）

| 任务 | 规则 | 状态 |
|---|---|---|
| 连续签到 | eventCode SJ10002 | ✅ 已验证 |
| 分享帖子 | +1/次，上限2分/天，领奖 SJ10003 | ✅ 已验证（2425→2427） |
| 发视频帖 | +10/条，上限20分/天 | ✅ 搬运发布链路已验证 |
| 发表优质帖/帖子加精/被推荐/评论加精/客户之声 | +20~+500 | ⚠️ 需官方人工审核，机器保证每天去发 |

## 2. 仓库结构

```
src/video_downloader.py  # B站搜索下载素材(关键词/数量可配)
src/video_maker.py       # 混剪: videos/raw 素材 → 每天2条竖屏成品
src/daily.py             # 每日任务主入口(签到/分享/搬运发视频/查分)
videos/raw/              # 素材(由 CI 自动从B站下载,每天刷新)
videos/out/              # 每天生成的成品(由 CI 生成)
videos/posted.json       # 已搬运的 source_id(防重复)
.github/workflows/daily.yml  # 每天08:00自动跑
```

关键接口（mobile-consumer-sapp.chery.cn，query `access_token+terminal=3` AES加密）：
- 登录：`POST uaa2c /api/v1/uaa/mobile/mobile-code-login`
- 签到：`POST /web/event/trigger {eventCode:SJ10002}`
- 分享：`POST /web/community/contents/{id}/share` + 领奖 `{eventCode:SJ10003}`
- 发视频：STS签名 → OSS直传 → `POST /web/community/contents {contentType:3, video:{url,duration,cover}}`
- 查分：`GET /web/user/current/details?access_token=&terminal=3`

借鉴：旧仓库 `jiuzihe36/chery/chery_sign.py` 的 APP_HEADERS（Dart UA + terminal=3 + event/trigger）是打通签到/分享的关键。

## 3. 维护（只需做一次）

- 取最新 token：打开 https://chery-token.pages.dev/ → 填手机号 → 获取验证码 → 获取 Token → 一键复制，
  然后去仓库 Settings → Secrets → Actions，把 `CHERY_TOKEN` 更新掉。token 有效期约2年，到期再取一次。
- 改素材关键词：编辑 `.github/workflows/daily.yml` 里的 `BILI_KEYWORD`。
- 改每天下载数量：编辑 `BILI_MAX`。
- 手动跑一次：仓库页 `Actions → 每日积分任务 → Run workflow`。

## 4. 安全提醒

- 私有仓库，不要公开。
- 素材来自 B站 公开视频（搜索关键词"奇瑞瑞虎8改装"），二次剪辑后发布，属合理使用。
- token 轮换后去 https://github.com/settings/tokens 删掉旧 `ghp_`。
