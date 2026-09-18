"""每日任务编排: 登录 → 签到 → 分享×2 → 发视频×2 → 写打卡记录。"""

import datetime
import os
import sys

sys.path.insert(0, os.path.dirname(__file__))
from chery_client import client_from_env
from video_maker import make_daily_videos

SHARE_TIMES = 2   # 分享上限2分/天
VIDEO_TIMES = 2   # 发视频上限20分/天(+10/条)


def log(msg):
    print("[%s] %s" % (datetime.datetime.now().strftime("%H:%M:%S"), msg),
          flush=True)


def main():
    log("任务开始")
    client = client_from_env()

    if not client.login():
        raise SystemExit("登录失败: 检查 CHERY_PHONE/CHERY_PASSWORD 或接口地址是否已填")
    log("登录成功")

    before = client.my_points()
    if before is not None:
        log("当前积分: %s" % before)

    # 1. 签到
    try:
        r = client.sign_in()
        log("签到完成: %s" % str(r)[:200])
    except Exception as e:
        log("签到失败: %s" % str(e)[:200])

    # 2. 分享帖子(上限2次)
    for i in range(SHARE_TIMES):
        try:
            client.share_post()
            log("分享 %d/%d 完成" % (i + 1, SHARE_TIMES))
        except Exception as e:
            log("分享失败: %s" % str(e)[:200])

    # 3. 发视频帖(上限2条,素材由 video_maker 混剪生成)
    videos = make_daily_videos()
    if not videos:
        log("没有可用视频素材: 请往 videos/raw/ 放2~3段奇瑞相关视频后重试")
    for i, v in enumerate(videos[:VIDEO_TIMES]):
        try:
            title = "奇瑞用车分享 %s(%d)" % (
                datetime.date.today().strftime("%m月%d日"), i + 1)
            client.publish_video(v, title)
            log("视频 %d/%d 发布完成: %s" % (i + 1, min(len(videos), VIDEO_TIMES), v))
        except Exception as e:
            log("视频发布失败: %s" % str(e)[:200])

    after = client.my_points()
    if after is not None:
        log("当前积分: %s" % after)

    log("全部任务完成")


if __name__ == "__main__":
    main()
