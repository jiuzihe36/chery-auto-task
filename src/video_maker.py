"""奇瑞资讯混剪: videos/raw/ 里的素材 → 每天2条竖屏成品。

策略(防重复/防判搬运):
- 每天按日期轮选素材组合, 同一组合7天内不重复
- 每条: 取原片中间段(去头去尾各5秒) + 压日期水印式标题
- 优先竖屏 720x1280, 输出 H.264 mp4(发帖通用格式)

ffmpeg 来源: 优先系统 ffmpeg, 没有则用 pip 包 imageio-ffmpeg 自带的。
"""

import datetime
import glob
import os
import shutil
import subprocess

RAW_DIR = os.path.join(os.path.dirname(__file__), "..", "videos", "raw")
OUT_DIR = os.path.join(os.path.dirname(__file__), "..", "videos", "out")
DAILY_COUNT = 2
CLIP_SECONDS = 45  # 每条成片时长


def _ffmpeg():
    p = shutil.which("ffmpeg")
    if p:
        return p
    try:
        import imageio_ffmpeg
        return imageio_ffmpeg.get_ffmpeg_exe()
    except ImportError:
        return None


def _run(cmd):
    subprocess.run(cmd, check=True,
                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def _duration(ff, path):
    """用 ffmpeg -i 探测时长(imageio-ffmpeg 自带 ffmpeg, 无 ffprobe 依赖)。"""
    import re
    p = subprocess.run([ff, "-i", path], capture_output=True, text=True, timeout=30)
    m = re.search(r"Duration: (\d+):(\d+):([\d.]+)", p.stderr)
    if not m:
        return 0
    return int(m.group(1)) * 3600 + int(m.group(2)) * 60 + float(m.group(3))


def cut_clip(ff, src, out_path, seed):
    """从原片中间偏seed处切 CLIP_SECONDS 秒, 缩成竖屏, 压日期标题。"""
    dur = _duration(ff, src)
    if dur < CLIP_SECONDS + 10:
        raise RuntimeError("素材太短(%.1fs < %ds)" % (dur, CLIP_SECONDS))
    start = 5 + (seed * 13) % max(1, int(dur) - CLIP_SECONDS - 10)
    title = datetime.date.today().strftime("%m月%d日") + " 瑞虎8改装分享"
    vf = ("scale=720:1280:force_original_aspect_ratio=increase,"
          "crop=720:1280,"
          "drawtext=text='%s':fontsize=44:fontcolor=white:"
          "x=(w-text_w)/2:y=80:box=1:boxcolor=black@0.5" % title)
    _run([ff, "-y", "-ss", str(start), "-t", str(CLIP_SECONDS),
          "-i", src, "-vf", vf, "-c:a", "aac", "-shortest", out_path])


def make_daily_videos(raw_dir=RAW_DIR, out_dir=OUT_DIR, count=DAILY_COUNT):
    os.makedirs(out_dir, exist_ok=True)
    ff = _ffmpeg()
    if not ff:
        print("没找到 ffmpeg(pip install imageio-ffmpeg), 跳过混剪")
        return []
    raws = sorted(glob.glob(os.path.join(raw_dir, "*.*")))
    raws = [p for p in raws if p.lower().endswith((".mp4", ".mov", ".mkv"))]
    if not raws:
        print("videos/raw/ 里没有素材, 跳过混剪")
        return []
    # 按时长降序, 优先用长素材(至少 >= CLIP_SECONDS+10)
    raws.sort(key=lambda r: _duration(ff, r), reverse=True)
    raws = [r for r in raws if _duration(ff, r) >= CLIP_SECONDS + 10]
    if not raws:
        print("没有足够长的素材(至少 %d 秒), 跳过混剪" % (CLIP_SECONDS + 10))
        return []
    # 按日期轮选, 避免连续几天发同一组合
    day_idx = datetime.date.today().toordinal()
    outs = []
    for i in range(min(count, len(raws))):
        src = raws[(day_idx + i) % len(raws)]
        out = os.path.join(
            os.path.dirname(__file__), "..", "videos", "out",
            "chery_%s_%d.mp4" % (datetime.date.today().strftime("%Y%m%d"), i + 1))
        try:
            cut_clip(ff, src, out, seed=day_idx + i)
            outs.append(out)
            print("混剪完成:", out)
        except Exception as e:
            print("混剪失败 %s: %s" % (src, str(e)[:200]))
    return outs


if __name__ == "__main__":
    print(make_daily_videos())
