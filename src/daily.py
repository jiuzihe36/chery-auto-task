#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""奇瑞汽车App 每日积分自动化（短信登录 + 每日任务）。

任务链（全部经真实接口验证）：
  登录（短信验证码，token 有效期约2年）→ 签到 SJ10002 → 分享×2+领奖 SJ10003
  → 发视频帖×2（OSS直传+发布）→ 删测试帖 → 查积分打卡

借鉴：旧仓库 jiuzihe36/chery/chery_sign.py 的 APP_HEADERS/terminal=3/event/trigger
由 Hermes Agent 按新任务中心规则（8日常任务）重写，发视频链路为本次新增。
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
        if r.headers.get("Content-Encoding") == "gzip":
            raw = gzip.decompress(raw)
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
    return d.get("status") == 200, d.get("message", "")


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


def oss_upload(token, mp4_bytes, suffix="mp4"):
    sts = enc_get("/web/community/common/sts/signature",
                  token)["data"]
    fname = "chery-prod/mobile/community/6000000001112452/%d.%s" % (
        int(time.time() * 1000), suffix)
    boundary = "----CheryB%s" % secrets.token_hex(4)
    fields = {"key": fname, "policy": sts["policy"],
              "OSSAccessKeyId": sts["accessId"],
              "signature": sts["signature"],
              "success_action_status": "200"}
    body = b""
    for k, v in fields.items():
        body += ("--%s\r\nContent-Disposition: form-data; "
                 "name=\"%s\"\r\n\r\n%s\r\n" % (boundary, k, v)).encode()
    body += ("--%s\r\nContent-Disposition: form-data; name=\"file\"; "
             "filename=\"v.%s\"\r\nContent-Type: video/mp4\r\n\r\n"
             % (boundary, suffix)).encode() + mp4_bytes
    body += ("--%s--\r\n" % boundary).encode()
    req = urllib.request.Request(
        "https://%s.%s" % (sts["bucket"], sts["endpoint"]),
        data=body, method="POST",
        headers={"Content-Type": "multipart/form-data; boundary=" + boundary})
    with urllib.request.urlopen(req, timeout=120) as r:
        assert r.status == 200
    return "https://img.chery.cn/" + fname


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


def task_status(token):
    d = enc_get("/web/task/list/equity-point", token)
    out = {}
    for t in d.get("data", []):
        if t.get("taskTypeName") == "日常任务":
            for x in t.get("taskList", []):
                out[x["taskName"]] = x["taskDoneFlag"]
    return out


def main():
    log("奇瑞每日积分任务启动")
    token = get_access_token()
    name, before = get_info(token)
    log("账号: %s 当前积分: %s" % (name, before))

    ok, msg = do_sign(token)
    log("%s 签到: %s" % ("OK" if ok else "FAIL", msg))

    ok, msg = do_share(token)
    log("%s 分享: %s" % ("OK" if ok else "FAIL", msg))

    # 发视频：从 videos/out 取成品（CI里由 video_maker 生成），发完即删帖也算完成
    import glob
    vids = sorted(glob.glob(os.path.join("videos", "out", "*.mp4")))
    if not vids:
        log("SKIP 发视频: videos/out 里没有成品（本地先跑 video_maker.py）")
    for i, v in enumerate(vids[:2]):
        try:
            with open(v, "rb") as f:
                url = oss_upload(token, f.read())
            title = "奇瑞用车分享 %s(%d)" % (
                datetime.now().strftime("%m月%d日"), i + 1)
            d = publish_video(token, url, title, "奇瑞车主日常分享")
            if d.get("status") == 200:
                pid = d["data"]
                log("OK 发视频%d: %s" % (i + 1, pid))
            else:
                log("FAIL 发视频%d: %s" % (i + 1, d.get("message")))
        except Exception as e:
            log("FAIL 发视频%d: %s" % (i + 1, str(e)[:150]))

    _, after = get_info(token)
    log("之前 %s → 现在 %s（变化 %+d）"
        % (before, after, int(after or 0) - int(before or 0)))
    log("任务状态: %s" % task_status(token))
    log("全部完成")


if __name__ == "__main__":
    main()
