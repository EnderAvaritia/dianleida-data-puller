"""
验证 cookies 是否仍然有效，无需打开浏览器窗口
"""

import io
import json
import sys
from pathlib import Path

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

from playwright.sync_api import sync_playwright

COOKIE_FILE = Path("cookies.json")
BASE_URL = "https://www.dianleida.net"


def check_login():
    if not COOKIE_FILE.exists():
        print("[FAIL] cookies.json 不存在，请先运行 login.py")
        return False

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(locale="zh-CN")
        page = context.new_page()

        with open(COOKIE_FILE, encoding="utf-8") as f:
            cookies = json.load(f)
        context.add_cookies(cookies)
        print(f"[OK] 已加载 {len(cookies)} 个 cookie")

        page.goto(BASE_URL, wait_until="domcontentloaded")
        page.wait_for_timeout(5000)

        body = page.text_content("body") or ""
        has_workspace = "工作台" in body
        has_login_btn = "登录" in body and "注册" in body and "dld_user" not in str(context.cookies())

        browser.close()

        if has_workspace:
            print("[OK] Cookie 有效，已登录状态")
            return True
        else:
            print("[FAIL] Cookie 已过期，请重新运行 login.py")
            return False


if __name__ == "__main__":
    check_login()
