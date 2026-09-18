#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""奇瑞汽车App 每日积分自动化（短信登录 + 每日任务）。

任务链（全部经真实接口验证）：
  token 登录（有效期约2年）→ 签到 SJ10002 → 分享×2+领奖 SJ10003
  → 搬运发视频×2（从社区扒别人视频→二次剪辑→OSS直传→发布，不删除）
  → 查积分打卡

搬运策略：每天从社区广场扒最新视频帖（排除自己发过的），下载后二次剪辑
（去头去尾、转竖屏720x1280、压日期标题），已搬运的 source_id 记入 posted.json，
同一原帖不重复搬。搬运视频与原帖内容相同但文件不同（重编码），属二次剪辑。

借鉴：旧仓库 jiuzihe36/chery/chery_sign.py 的 APP_HEADERS/terminal=3/event/trigger
由 Hermes Agent 按新任务中心规则（8日常任务）重写，搬运链路为本次新增。
"""
import base64
import gzip
import json
import os
import secrets
import sys
import time
import urllib.parse
import urllib.request
from datetime import datetime

from Crypto.Cipher import AES
from Crypto.Util.Padding import pad

UAA = "https://uaa2c.chery.cn"
BASE = "https://mobile-consumer-sapp.chery.cn"
AES_KEY = base64.b64decode("vVfnp9ozfDQyonMKuqgZUWjtdV+7PtBqtMCwJqz2HKQ=")

APP_HEADERS = {
    "user-agent": "Dart/2.19 (dart:io)",
    "appversioncode": "26030901",
    "accept": "application/json, text/plain, */*",
    "appversion": "3.6.9",
    "accept-language": "zh-CN,zh;q=0.9",
    # 注：不要加 accept-encoding: gzip，网关 gzip+加密体会截断 policy 等长字段
    "content-type": "application/json; charset=UTF-8",
    "agent": "android",
    "encryptflag": "true",
    "request-channel": "app",
    "host": "mobile-consumer-sapp.chery.cn",
}
UA_HEADERS = {"User-Agent": "Dart/2.19 (dart:io)",
              "Accept": "application/json, text/plain, */*"}


def log(msg):
    print("[%s] %s" % (datetime.now().strftime("%H:%M:%S"), msg), flush=True)


def aes_encrypt(plaintext):
    iv = secrets.token_bytes(16)
    ct = AES.new(AES_KEY, AES.MODE_CBC, iv).encrypt(
        pad(plaintext.encode("utf-8"), AES.block_size, style="pkcs7"))
    return base64.b64encode(iv + ct).decode().replace("+", "-")


def enc_token(token):
    return urllib.parse.quote(
        aes_encrypt("access_token=%s&terminal=3" % token), safe="")


def api(method, url, body=None, headers=None):
    req = urllib.request.Request(url, headers=headers or APP_HEADERS,
                                 data=body, method=method)
    with urllib.request.urlopen(req, timeout=30) as r:
        raw = r.read()
        # 服务端长字段(JSON)在gzip下会被网关截断，统一按明文解析
        return json.loads(raw)


def enc_post(path, token, payload):
    url = BASE + path + "?encryptParam=" + enc_token(token)
    body = aes_encrypt(json.dumps(payload, separators=(",", ":"))).encode()
    return api("POST", url, body)


def enc_get(path, token, query=""):
    url = BASE + path + "?encryptParam=" + enc_token(token)
    if query:
        url += "&" + query
    return api("GET", url)


# ---------- 登录 ----------

def send_sms(phone):
    body = json.dumps({"mobile": phone, "template": "login"}).encode()
    req = urllib.request.Request(
        UAA + "/api/v1/common/mobile/sms?client_id=cherygf", data=body,
        method="POST", headers={"Content-Type": "application/json",
                                "accept-language": "zh-CN,zh"})
    with urllib.request.urlopen(req, timeout=20) as r:
        return json.loads(r.read())


def login_by_sms(phone, code):
    body = json.dumps({"mobile": phone,
                       "verificationCode": code}).encode()
    req = urllib.request.Request(
        UAA + "/api/v1/uaa/mobile/mobile-code-login", data=body,
        method="POST", headers={"Content-Type": "application/json",
                                "accept-language": "zh-CN,zh"})
    with urllib.request.urlopen(req, timeout=20) as r:
        return json.loads(r.read())


def get_access_token():
    tok = os.environ.get("CHERY_TOKEN", "")
    if tok:
        return tok
    phone = os.environ.get("CHERY_PHONE", "")
    code = os.environ.get("CHERY_SMS_CODE", "")
    if phone and code:
        d = login_by_sms(phone, code)
        if d.get("status") == 200:
            return d["data"]["accessToken"]
        raise SystemExit("短信登录失败: %s" % d.get("message"))
    raise SystemExit("缺少 CHERY_TOKEN（或 CHERY_PHONE + CHERY_SMS_CODE）")


# ---------- 任务 ----------

def get_info(token):
    url = "%s/web/user/current/details?access_token=%s&terminal=3" % (BASE, token)
    req = urllib.request.Request(url, headers=UA_HEADERS)
    with urllib.request.urlopen(req, timeout=20) as r:
        d = json.loads(r.read())["data"]
    return d.get("displayName"), d.get("pointAccount", {}).get("payableBalance")


def trigger(token, event_code):
    return enc_post("/web/event/trigger", token, {"eventCode": event_code})


def do_sign(token):
    d = trigger(token, "SJ10002")
    ok, msg = d.get("status") == 200, d.get("message", "")
    if not ok:
        return False, msg
    # 查连续签到天数 + 可开礼盒（7/15/30/60/90/180/360/540/720/1000/1365/2000天）
    try:
        box = sign_box_status(token)
        if box.get("opened"):
            msg += "，开盒: %s" % "、".join(box["opened"])
        else:
            msg += "（连续%d天，%s）" % (box.get("days", "?"), box.get("next", ""))
    except Exception as e:
        msg += "（查礼盒失败: %s）" % str(e)[:60]
    return True, msg


def sign_box_status(token):
    """查签到礼盒：返回 {days, opened:[...], next}。可开的自动跳转抽奖页 prizeCode。"""
    import urllib.parse
    import urllib.request

    def enc_get_full(path, params):
        q = "access_token=%s&terminal=3" % token
        for k, v in params.items():
            q += "&%s=%s" % (k, v)
        enc = aes_encrypt(q).replace("+", "-")
        url = BASE + path + "?encryptParam=" + urllib.parse.quote(enc, safe="")
        req = urllib.request.Request(url, headers=APP_HEADERS)
        with urllib.request.urlopen(req, timeout=20) as r:
            return json.loads(r.read())

    d = enc_get_full("/web/task/record/sign-in/lottery",
                     {"taskCode": "SignUpLottery03"})["data"]
    days = d.get("continualDays", 0)
    opened, nxt = [], ""
    stages = sorted(e["stage"] for e in d.get("equityList", []))
    reached = [s for s in stages if s <= days]
    if reached:
        last = reached[-1]
        for e in d["equityList"]:
            if e["stage"] == last and e.get("prizeCode"):
                opened.append("第%d天礼盒(prizeCode=%s，去App抽奖页开)"
                              % (last, e["prizeCode"]))
    todo = [s for s in stages if s > days]
    if todo:
        nxt = "下个礼盒第%d天，还差%d天" % (todo[0], todo[0] - days)
    else:
        nxt = "已开完所有礼盒"
    return {"days": days, "opened": opened, "next": nxt}


def do_share(token, times=2):
    q = urllib.parse.quote(aes_encrypt(
        "pageNo=1&pageSize=10&access_token=%s&terminal=3" % token), safe="")
    url = BASE + "/web/community/recommend/contents?encryptParam=" + q
    d = api("GET", url)
    arts = (d.get("data") or {}).get("data", [])
    if not arts:
        return False, "无推荐文章"
    ok = 0
    for i, a in enumerate(arts[:times]):
        aid = str(a["content"]["id"])
        sd = enc_post("/web/community/contents/%s/share" % aid,
                      token, {"contentId": aid})
        if sd.get("status") == 200:
            rd = trigger(token, "SJ10003")
            if rd.get("status") == 200:
                ok += 1
        if i < times - 1:
            time.sleep(2)
    return ok > 0, "分享成功%d/%d次" % (ok, times)


def oss_upload(token, mp4_bytes, suffix="mp4", tries=5):
    import time as _t
    import http.client as _hc
    last = None
    for i in range(tries):  # STS 签名有时效，失败就取新签名重试
        try:
            sts = enc_get("/web/community/common/sts/signature",
                          token)["data"]
            fname = "chery-prod/mobile/community/6000000001112452/%d_%d.%s" % (
                int(_t.time() * 1000), i, suffix)
            boundary = "----CheryB%s" % secrets.token_hex(4)
            fields = {"key": fname, "policy": sts["policy"],
                      "OSSAccessKeyId": sts["accessId"],
                      "signature": sts["signature"],
                      "success_action_status": "200"}
            parts = []
            for k, v in fields.items():
                parts.append(
                    ("--%s\r\nContent-Disposition: form-data; name=\"%s\"\r\n\r\n%s\r\n"
                     % (boundary, k, v)).encode())
            parts.append(
                ("--%s\r\nContent-Disposition: form-data; name=\"file\"; "
                 "filename=\"v.%s\"\r\nContent-Type: video/mp4\r\n\r\n"
                 % (boundary, suffix)).encode() + mp4_bytes)
            # multipart 规范: 最后 boundary 前必须 CRLF(OSS 严格,缺了报 Malformed)
            parts.append(("\r\n--%s--\r\n" % boundary).encode())
            body = b"".join(parts)
            host = "%s.%s" % (sts["bucket"], sts["endpoint"])
            conn = _hc.HTTPSConnection(host, timeout=180)
            conn.request("POST", "/", body=body,
                         headers={"Content-Type":
                                  "multipart/form-data; boundary=" + boundary,
                                  "Content-Length": str(len(body))})
            r = conn.getresponse()
            rb = r.read()
            conn.close()
            if r.status == 200:
                return "https://img.chery.cn/" + fname
            raise RuntimeError("OSS %s: %s" % (r.status, rb[:200]))
        except Exception as e:
            last = e
            _t.sleep(1 + i * 2)  # 指数退避
    raise last


def publish_video(token, video_url, title, detail, duration=5):
    payload = {"title": title, "detail": detail, "contentType": 3,
               "video": {"url": video_url, "duration": duration,
                         "cover": video_url},
               "channel": 1}
    return enc_post("/web/community/contents", token, payload)


def delete_post(token, post_id):
    url = "%s/web/community/contents/%s?encryptParam=%s" % (
        BASE, post_id, enc_token(token))
    req = urllib.request.Request(url, headers=APP_HEADERS, method="DELETE")
    with urllib.request.urlopen(req, timeout=20) as r:
        return json.loads(r.read())


MY_ACCOUNT_ID = "6000000001112452"
POSTED_PATH = os.path.join(os.path.dirname(__file__), "..", "videos",
                           "posted.json")


def load_posted():
    try:
        with open(POSTED_PATH) as f:
            return json.load(f)
    except Exception:
        return {"source_ids": [], "posts": []}


def save_posted(data):
    os.makedirs(os.path.dirname(POSTED_PATH), exist_ok=True)
    with open(POSTED_PATH, "w") as f:
        json.dump(data, f, ensure_ascii=False, indent=1)


def square_videos(token, page_size=30):
    """从社区广场拉最新视频帖（排除自己发的）。"""
    q = urllib.parse.quote(aes_encrypt(
        "pageNo=1&pageSize=%d&access_token=%s&terminal=3"
        % (page_size, token)), safe="")
    url = BASE + "/web/community/contents/square-newest-contents?encryptParam=" + q
    d = api("GET", url)
    out = []
    for c in (d.get("data") or {}).get("data", []):
        if c.get("contentType") != 3:
            continue
        if not (c.get("video") or {}).get("url"):
            continue
        if str(c.get("authorId")) == MY_ACCOUNT_ID:
            continue
        if not str(c.get("id", "")).isdigit():
            continue
        out.append(c)
    return out


def download_file(url, limit_mb=150, timeout=120):
    # OSS 的 URL 含未编码特殊字符时先 quote path 部分
    parts = urllib.parse.urlsplit(url)
    url = urllib.parse.urlunsplit(
        (parts.scheme, parts.netloc,
         urllib.parse.quote(parts.path, safe="/"),
         parts.query, parts.fragment))
    req = urllib.request.Request(
        url, headers={"User-Agent": "Mozilla/5.0",
                      "Referer": "https://hybrid-sapp.chery.cn/"})
    buf = b""
    with urllib.request.urlopen(req, timeout=timeout) as r:
        while True:
            chunk = r.read(1 << 20)
            if not chunk:
                break
            buf += chunk
            if len(buf) > limit_mb * 1024 * 1024:
                break
    return buf


def ffmpeg_exe():
    import shutil
    p = shutil.which("ffmpeg")
    if p:
        return p
    try:
        import imageio_ffmpeg
        return imageio_ffmpeg.get_ffmpeg_exe()
    except ImportError:
        return None


def probe_duration(ff, path):
    import re
    import subprocess
    p = subprocess.run([ff, "-i", path], capture_output=True, text=True,
                       timeout=30)
    m = re.search(r"Duration: (\d+):(\d+):([\d.]+)", p.stderr)
    if not m:
        return 0
    return int(m.group(1)) * 3600 + int(m.group(2)) * 60 + float(m.group(3))


def reedit(ff, src, dst, title):
    """二次剪辑：去头去尾各3秒，转竖屏720x1280（不压字：CI 无中文字体）。"""
    import subprocess
    dur = probe_duration(ff, src)
    if dur <= 0:
        raise RuntimeError("读不到视频时长")
    start = 3 if dur > 8 else 0
    length = max(5, min(40, dur - start - (3 if dur > 8 else 0)))
    vf = ("scale=720:1280:force_original_aspect_ratio=increase,"
          "crop=720:1280")
    p = subprocess.run(
        [ff, "-y", "-ss", str(start), "-t", str(length), "-i", src,
         "-vf", vf, "-c:v", "libx264", "-preset", "veryfast", "-crf", "26",
         "-c:a", "aac", "-shortest", dst],
        capture_output=True, text=True, timeout=300)
    if p.returncode != 0:
        raise RuntimeError("ffmpeg失败: %s" % p.stderr[-300:])
    return length


def do_repost_videos(token, count=2):
    """搬运发视频：扒广场视频→二次剪辑→上传→发布（不删除）。返回(成功数, 说明)。"""
    import tempfile
    posted = load_posted()
    done_ids = set(posted.get("source_ids", []))
    cands = [c for c in square_videos(token) if str(c["id"]) not in done_ids]
    if not cands:
        return False, "广场上没有新的可搬运视频"
    ff = ffmpeg_exe()
    if not ff:
        return False, "没找到 ffmpeg"
    ok = 0
    for c in cands:
        if ok >= count:
            break
        sid = str(c["id"])
        try:
            raw = download_file(c["video"]["url"])
            # 有些"视频帖"实为 PNG/图片伪装，跳过
            if raw[:8] == b"\x89PNG\r\n\x1a\n" or raw[:4] in (b"GIF8", b"\xff\xd8\xff"):
                log("SKIP 原帖%s: 实为图片伪装 (%s)" % (sid, raw[:4]))
                continue
            if len(raw) < 100 * 1024:
                continue
            with tempfile.TemporaryDirectory() as td:
                src = os.path.join(td, "src.mp4")
                dst = os.path.join(td, "out.mp4")
                with open(src, "wb") as f:
                    f.write(raw)
                title = datetime.now().strftime("%m月%d日") + " 车友分享"
                length = reedit(ff, src, dst, title)
                with open(dst, "rb") as f:
                    url = oss_upload(token, f.read())
            detail = "看到车友「%s」分享不错，转发给大家" % (
                (c.get("title") or "精彩视频")[:20])
            d = publish_video(token, url, (c.get("title") or "车友分享")[:25],
                              detail, duration=int(length))
            if d.get("status") == 200:
                ok += 1
                posted.setdefault("source_ids", []).append(sid)
                posted.setdefault("posts", []).append(
                    {"source_id": sid, "post_id": d["data"],
                     "date": datetime.now().strftime("%Y-%m-%d")})
                save_posted(posted)
                log("OK 搬运视频%d: 原帖%s → 新帖%s" % (ok, sid, d["data"]))
            else:
                log("FAIL 搬运发布: %s" % d.get("message"))
        except Exception as e:
            log("FAIL 搬运原帖%s: %s" % (sid, str(e)[:150]))
        time.sleep(2)
    save_posted(posted)
    return ok > 0, "搬运发视频成功%d/%d条" % (ok, count)


def task_status(token):
    d = enc_get("/web/task/list/equity-point", token)
    out = {}
    for t in d.get("data", []):
        if t.get("taskTypeName") == "日常任务":
            for x in t.get("taskList", []):
                out[x["taskName"]] = x["taskDoneFlag"]
    return out


def main():
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--quick-only", action="store_true",
                        help="只跑签到+分享（快任务优先）")
    parser.add_argument("--video-only", action="store_true",
                        help="只跑发视频（慢任务放后）")
    args = parser.parse_args()

    log("奇瑞每日积分任务启动")
    token = get_access_token()
    name, before = get_info(token)
    log("账号: %s 当前积分: %s" % (name, before))

    if not args.video_only:
        ok, msg = do_sign(token)
        log("%s 签到: %s" % ("OK" if ok else "FAIL", msg))

        ok, msg = do_share(token)
        log("%s 分享: %s" % ("OK" if ok else "FAIL", msg))

    if not args.quick_only:
        # 发视频：从社区广场搬运别人视频→二次剪辑→发布（不删除，删了扣分）
        ok, msg = do_repost_videos(token)
        log("%s 发视频: %s" % ("OK" if ok else "FAIL", msg))

    _, after = get_info(token)
    log("之前 %s → 现在 %s（变化 %+d）"
        % (before, after, int(after or 0) - int(before or 0)))
    log("任务状态: %s" % task_status(token))
    log("全部完成")


if __name__ == "__main__":
    main()
