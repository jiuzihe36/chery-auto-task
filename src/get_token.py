#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""手动获取奇瑞 token（配合 .github/workflows/get-token.yml 在 GitHub 上点两次）。

第一次空验证码跑 → 调用 send_sms 发短信到手机。
收到短信后，第二次填上验证码跑 → 打印 accessToken，复制去存 Secrets。
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from daily import login_by_sms, send_sms

phone = os.environ.get("PHONE", "").strip()
code = os.environ.get("SMS_CODE", "").strip()

if not phone:
    raise SystemExit("缺少手机号（workflow 里 phone 输入框没填）")

if not code:
    d = send_sms(phone)
    print("发短信返回: %s" % d)
    if d.get("status") == 200:
        print("短信已发送，请看手机验证码，然后再跑一次并填上 sms_code。")
    else:
        raise SystemExit("发短信失败: %s" % d.get("message"))
else:
    d = login_by_sms(phone, code)
    if d.get("status") != 200:
        raise SystemExit("登录失败: %s" % d.get("message"))
    data = d["data"]
    print("登录成功！把下面这串存到仓库 Secrets，名字叫 CHERY_TOKEN：")
    print("TOKEN_BEGIN")
    print(data["accessToken"])
    print("TOKEN_END")
    print("有效期到: %s" % data.get("refreshExpireAt", "未知"))
    print("注意：复制完后去 Actions 页面删掉这次运行的日志，避免 token 泄露。")
