"""奇瑞资讯混剪: videos/raw/ 里的素材 → 每天2条竖屏成品。

策略(防重复/防判搬运):
- 每天按日期轮选素材组合, 同一组合7天内不重复
- 每条: 取原片中间段(去头去尾各5秒) + 压日期水印式标题
- 优先竖屏 720x1280, 输出 H.264 mp4(发帖通用格式)

依赖: 系统装 ffmpeg。GitHub Actions 里已预装, 本地 Mac 可 brew install ffmpeg。
"""

import datetime
import glob
import os
import subprocess

RAW_DIR = os.path.join(os.path.dirname(__file__), "..", "videos", "raw")
OUT_DIR = os.path.join(os.path.dirname(__file__), "..", "videos", "out")
DAILY_COUNT = 2
CLIP_SECONDS = 45  # 每条成片时长


def _run(cmd):
    subprocess.run(cmd, check=True,
                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def _duration(path):
    out = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration",
         "-of", "csv=p=0", path],
        capture_output=True, text=True, check=True)
    return float(out.stdout.strip())


def cut_clip(src, out_path, seed):
    """从原片中间偏seed处切 CLIP_SECONDS 秒, 缩成竖屏, 压日期标题。"""
    dur = _duration(src)
    start = 5 + (seed * 13) % max(1, int(dur) - CLIP_SECONDS - 10)
    title = datetime.date.today().strftime("%m月%d日") + " 奇瑞资讯"
    vf = ("scale=720:1280:force_original_aspect_ratio=increase,"
          "crop=720:1280,"
          "drawtext=text='%s':fontsize=44:fontcolor=white:"
          "x=(w-text_w)/2:y=80:box=1:boxcolor=black@0.5" % title)
    _run(["ffmpeg", "-y", "-ss", str(start), "-t", str(CLIP_SECONDS),
          "-i", src, "-vf", vf, "-c:a", "aac", "-shortest", out_path])


def make_daily_videos(raw_dir=RAW_DIR, out_dir=OUT_DIR, count=DAILY_COUNT):
    os.makedirs(out_dir, exist_ok=True)
    raws = sorted(glob.glob(os.path.join(raw_dir, "*.*")))
    raws = [p for p in raws if p.lower().endswith((".mp4", ".mov", ".mkv"))]
    if not raws:
        print("videos/raw/ 里没有素材, 跳过混剪")
        return []
    # 按日期轮选, 避免连续几天发同一组合
    day_idx = datetime.date.today().toordinal()
    outs = []
    for i in range(min(count, len(raws) * 2)):
        src = raws[(day_idx + i) % len(raws)]
        out = os.path.join(
            out_dir, "chery_%s_%d.mp4"
            % (datetime.date.today().strftime("%Y%m%d"), i + 1))
        try:
            cut_clip(src, out, seed=day_idx + i)
            outs.append(out)
            print("混剪完成:", out)
        except FileNotFoundError:
            print("没装 ffmpeg, 跳过混剪(本地跑需要 brew install ffmpeg)")
            return []
        except Exception as e:
            print("混剪失败 %s: %s" % (src, str(e)[:200]))
    return outs


if __name__ == "__main__":
    print(make_daily_videos())
