"""奇瑞汽车App 接口封装。

【必须做的一件事】把抓包得到的真实地址填到下面 BASE_URL / ENDPOINTS：
  1. 电脑装 Charles（或安卓装 HttpCanary），手机 WiFi 挂代理
  2. 在奇瑞App里依次操作：登录、签到、分享帖子、发视频帖
  3. 把抓到的 https 域名填给 BASE_URL，路径填给 ENDPOINTS 对应项
填完提交一次，以后每天自动跑，不用再抓。
"""

import json
import os
import urllib.request

# TODO(抓包后填): 例如 "https://app-api.chery.com"
BASE_URL = "https://__FILL_AFTER_CAPTURE__"

# TODO(抓包后填): 每个 key 对应抓到的 path，例如 "/api/v1/signin"
ENDPOINTS = {
    "login": "/__FILL__/login",       # 手机号+密码登录
    "sign_in": "/__FILL__/sign-in",   # 每日签到
    "share": "/__FILL__/share",       # 分享帖子
    "publish_video": "/__FILL__/publish-video",  # 发视频帖
    "user_info": "/__FILL__/user-info",  # 查积分(用于打卡记录)
}


class CheryClient:
    def __init__(self, phone, password, base_url=BASE_URL, timeout=20):
        self.phone = phone
        self.password = password
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self.token = None

    def _post(self, path, data=None, need_auth=True):
        url = self.base_url + path
        body = json.dumps(data or {}).encode("utf-8")
        headers = {"Content-Type": "application/json"}
        if need_auth and self.token:
            headers["Authorization"] = "Bearer " + self.token
        req = urllib.request.Request(url, data=body, headers=headers, method="POST")
        with urllib.request.urlopen(req, timeout=self.timeout) as r:
            return json.load(r)

    def _get(self, path, need_auth=True):
        url = self.base_url + path
        headers = {}
        if need_auth and self.token:
            headers["Authorization"] = "Bearer " + self.token
        req = urllib.request.Request(url, headers=headers, method="GET")
        with urllib.request.urlopen(req, timeout=self.timeout) as r:
            return json.load(r)

    def login(self):
        """手机号+密码登录，返回 True/False。"""
        resp = self._post(ENDPOINTS["login"],
                          {"phone": self.phone, "password": self.password},
                          need_auth=False)
        # 下面按常见字段取值，抓包后如字段名不同改这里即可
        token = resp.get("token") or resp.get("data", {}).get("token") \
            if isinstance(resp, dict) else None
        if token:
            self.token = token
            return True
        print("登录返回(未取到token):", json.dumps(resp, ensure_ascii=False)[:500])
        return False

    def sign_in(self):
        """每日签到。"""
        return self._post(ENDPOINTS["sign_in"], {})

    def share_post(self, post_id="home"):
        """分享帖子 +1，上限2分/天。"""
        return self._post(ENDPOINTS["share"], {"post_id": post_id})

    def publish_video(self, video_path, title, cover_path=None):
        """发视频帖 +10，上限20分/天(每天2条)。

        说明: 绝大多数App发视频分两步(先上传文件拿fileId再发布)。
        抓包后若是两步，把这里拆成 upload + publish 即可，tasks.py 不用改。
        """
        return self._post(ENDPOINTS["publish_video"],
                          {"title": title, "video": video_path,
                           "cover": cover_path or ""})

    def my_points(self):
        """查当前积分，用于打卡记录。失败返回 None。"""
        try:
            resp = self._get(ENDPOINTS["user_info"])
            if isinstance(resp, dict):
                for k in ("points", "score", "integral"):
                    if k in resp:
                        return resp[k]
                d = resp.get("data", {})
                if isinstance(d, dict):
                    for k in ("points", "score", "integral"):
                        if k in d:
                            return d[k]
            return None
        except Exception as e:
            print("查积分失败(不影响主流程):", str(e)[:200])
            return None


def client_from_env():
    phone = os.environ.get("CHERY_PHONE", "")
    password = os.environ.get("CHERY_PASSWORD", "")
    if not phone or not password:
        raise SystemExit("缺少 Secrets: 请先在仓库 Settings→Secrets 里建 CHERY_PHONE / CHERY_PASSWORD")
    return CheryClient(phone, password)
