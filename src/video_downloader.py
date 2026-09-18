"""奇瑞瑞虎8改装视频素材自动下载 + CI 自动混剪 + 每日发帖。

流程（GitHub Actions 每日 08:00 北京时间）:
  search_bilibili("奇瑞瑞虎8改装") → 下载 top-6 视频到 videos/raw/
  → video_maker.py 混剪 2 条竖屏成品到 videos/out/
  → daily.py 发帖 2 条 → 查积分

依赖（pip install）: pycryptodome imageio-ffmpeg requests

安全: 搜索关键词和下载量通过环境变量 BILI_KEYWORD / BILI_MAX 控制,
默认关键词"奇瑞瑞虎8改装", 默认最多下 6 条。
"""
import datetime
import glob
import json
import os
import re
import shutil
import subprocess
import time
import urllib.request
import urllib.parse
import urllib.error

RAW_DIR = os.path.join(os.path.dirname(__file__), "..", "videos", "raw")
MAX_VIDEOS = int(os.environ.get("BILI_MAX", "6"))
KEYWORD = os.environ.get("BILI_KEYWORD", "奇瑞瑞虎8改装")


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
    probe = shutil.which("ffprobe")
    if probe:
        out = subprocess.run(
            [probe, "-v", "error", "-show_entries", "format=duration",
             "-of", "csv=p=0", path],
            capture_output=True, text=True, check=True)
        return float(out.stdout.strip())
    return 120.0


def cut_clip(ff, src, out_path, seed):
    """从原片中间偏seed处切 45秒, 缩成竖屏, 压日期标题。"""
    dur = _duration(ff, src)
    start = 5 + (seed * 13) % max(1, int(dur) - 45 - 10)
    title = datetime.date.today().strftime("%m月%d日") + " 瑞虎8改装分享"
    vf = ("scale=720:1280:force_original_aspect_ratio=increase,"
          "crop=720:1280,"
          "drawtext=text='%s':fontsize=44:fontcolor=white:"
          "x=(w-text_w)/2:y=80:box=1:boxcolor=black@0.5" % title)
    _run([ff, "-y", "-ss", str(start), "-t", "45",
          "-i", src, "-vf", vf, "-c:a", "aac", "-shortest", out_path])


def make_daily_videos(raw_dir=RAW_DIR, count=2):
    os.makedirs(raw_dir, exist_ok=True)
    os.makedirs(os.path.join(os.path.dirname(__file__), "..", "videos", "out"),
                exist_ok=True)
    ff = _ffmpeg()
    if not ff:
        print("没找到 ffmpeg(pip install imageio-ffmpeg), 跳过混剪")
        return []
    raws = sorted(glob.glob(os.path.join(raw_dir, "*.*")))
    raws = [p for p in raws if p.lower().endswith((".mp4", ".mov", ".mkv"))]
    if not raws:
        print("videos/raw/ 里没有素材, 跳过混剪")
        return []
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


# ---------- Bilibili 搜索 + 下载 ----------

def _bilibili_search(keyword, pages=1):
    """调用 B站 公开搜索 API 返回视频列表 [{'bvid', 'title', ...}]。"""
    url = ("https://api.bilibili.com/x/web-interface/search/type?"
           "search_type=video&keyword=%s&page=%d"
           % (urllib.parse.quote(keyword), pages))
    req = urllib.request.Request(url, headers={
        "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Accept": "application/json, text/plain, */*",
        "Referer": "https://search.bilibili.com/",
        "Accept-Language": "zh-CN,zh;q=0.9"})
    for _ in range(3):
        try:
            with urllib.request.urlopen(req, timeout=15) as r:
                d = json.loads(r.read())
            if d.get("code") == 0:
                return d.get("data", {}).get("result", []) or []
        except urllib.error.HTTPError as e:
            if e.code == 412:
                time.sleep(2)
                continue
            raise
        time.sleep(1)
    return []


def _bilibili_play_url(bvid):
    """用 B站 API 拿实际播放 URL(无需网页解析)。

    网页 __playinfo__ 已被 B站 移除，改用 pagelist + playurl 接口。
    """
    # 1. 拿 cid
    cid_url = "https://api.bilibili.com/x/player/pagelist?bvid=" + bvid
    req = urllib.request.Request(cid_url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=10) as r:
        d = json.loads(r.read())
    if not d.get("data"):
        return None
    cid = d["data"][0]["cid"]
    # 2. 拿 playurl
    u = ("https://api.bilibili.com/x/player/playurl?bvid=%s&cid=%s&qn=80"
         "&type=&otype=json&fnval=0" % (bvid, cid))
    req = urllib.request.Request(u, headers={"User-Agent": "Mozilla/5.0",
                                              "Referer": "https://www.bilibili.com/"})
    with urllib.request.urlopen(req, timeout=10) as r:
        d = json.loads(r.read())
    data = d.get("data", {})
    if "durl" in data and data["durl"]:
        return data["durl"][0]["url"]
    dash = data.get("dash", {})
    for v in dash.get("video", []):
        if v.get("baseUrl"):
            return v["baseUrl"]
    return None


def download_bilibili_video(url, out_path):
    """下载一个视频到 out_path(自动重试)。"""
    import time as _t
    for i in range(3):
        try:
            req = urllib.request.Request(url, headers={
                "User-Agent": "Mozilla/5.0",
                "Referer": "https://www.bilibili.com/"})
            with urllib.request.urlopen(req, timeout=120) as r:
                with open(out_path, "wb") as f:
                    while True:
                        chunk = r.read(1 << 20)
                        if not chunk:
                            break
                        f.write(chunk)
            return True
        except Exception as e:
            print("下载重试 %d: %r" % (i + 1, str(e)[:120]))
            _t.sleep(2)
    return False


def fetch_videos(keyword=KEYWORD, max_videos=MAX_VIDEOS):
    """搜索并下载视频到 videos/raw/, 返回新下载的文件列表。"""
    os.makedirs(RAW_DIR, exist_ok=True)
    existing = set(os.path.basename(p) for p in glob.glob(os.path.join(RAW_DIR, "*.*")))
    videos = _bilibili_search(keyword)
    downloaded = []
    for v in videos:
        bvid = v.get("bvid") or v.get("bvid")
        title = v.get("title", "unknown")[:40]
        print("搜到: %s (%s)" % (title, bvid))
        # 去重: 标题或 bvid 已存在
        safe = title.replace("/", "_").replace("\\", "_")
        if safe in existing or bvid in existing:
            print("  跳过(已存在)")
            continue
        play_url = _bilibili_play_url(bvid)
        if not play_url:
            print("  拿不到播放地址, 跳过")
            continue
        out_name = "%s_%s.mp4" % (datetime.date.today().strftime("%Y%m%d"), bvid)
        out_path = os.path.join(RAW_DIR, out_name)
        if download_bilibili_video(play_url, out_path):
            downloaded.append(out_path)
            print("  下载完成: %s" % out_path)
            existing.add(safe)
            existing.add(bvid)
        if len(downloaded) >= max_videos:
            break
    return downloaded


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--download-only", action="store_true", help="只下载不混剪")
    args = parser.parse_args()
    print("=== 下载素材: keyword=%s max=%d ===" % (KEYWORD, MAX_VIDEOS))
    fetched = fetch_videos()
    print("下载完成: %d 个" % len(fetched))
    if not args.download_only:
        print("=== 混剪 ===")
        outs = make_daily_videos()
        print("混剪完成: %d 条成品" % len(outs))