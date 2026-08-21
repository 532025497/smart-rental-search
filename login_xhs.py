# -*- coding: utf-8 -*-
"""小红书扫码登录 — 生成 Playwright storage_state

用法:
    .venv/bin/python login_xhs.py

流程:
    1. 打开小红书登录页（有头浏览器）
    2. 手机扫码确认登录
    3. 登录成功后自动保存 cookie 到 data/xhs_state.json
    4. 之后 XiaohongshuCollector 复用该文件保持登录态
"""
import os
import sys
import time

from playwright.sync_api import sync_playwright

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
STATE_PATH = os.path.join(BASE_DIR, "data", "xhs_state.json")


def main() -> int:
    os.makedirs(os.path.dirname(STATE_PATH), exist_ok=True)

    with sync_playwright() as p:
        browser = p.chromium.launch(channel="chrome", headless=False)
        ctx = browser.new_context(
            viewport={"width": 1280, "height": 800},
            user_agent=("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                        "AppleWebKit/537.36 (KHTML, like Gecko) "
                        "Chrome/120.0.0.0 Safari/537.36"),
            locale="zh-CN",
        )
        page = ctx.new_page()
        page.goto("https://www.xiaohongshu.com", wait_until="domcontentloaded")

        print("=" * 50)
        print("  请在打开的浏览器窗口中扫码登录小红书")
        print("  登录成功后本脚本会自动保存登录态并退出")
        print("=" * 50)

        # 轮询等待登录成功: 出现用户头像/进入首页
        deadline = time.time() + 300  # 最多等5分钟
        logged_in = False
        while time.time() < deadline:
            try:
                # 登录成功后页面上会出现用户侧边栏/头像元素
                if page.locator(".user.side-bar-component, .login-btn, "
                                "img[alt='用户头像'], .avatar").first.is_visible(
                    timeout=2000
                ):
                    cookies = ctx.cookies()
                    has_session = any(c["name"] in ("web_session", "a1")
                                      for c in cookies)
                    if has_session:
                        logged_in = True
                        break
            except Exception:
                pass
            time.sleep(2)

        if not logged_in:
            print("[失败] 5分钟内未检测到登录，退出。请重试。")
            browser.close()
            return 1

        # 稍等页面稳定再保存
        time.sleep(3)
        ctx.storage_state(path=STATE_PATH)
        browser.close()

    print(f"[成功] 登录态已保存: {STATE_PATH}")
    print("现在可以运行真实采集了。cookie 一般可复用数天~数周，")
    print("失效后重新运行本脚本扫码一次即可。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
