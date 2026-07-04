"""
店雷达登录脚本 — Playwright 自动化登录 + Cookie 持久化
首次运行会打开浏览器窗口，手动扫码/账号登录后自动保存 cookie
后续运行直接加载 cookie，无需重复登录
"""

import io
import json
import os
import re
import sys
from pathlib import Path

# 强制 stdout 使用 utf-8，避免 gbk 编码报错
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

from playwright.sync_api import sync_playwright

COOKIE_FILE = Path("cookies.json")
BASE_URL = "https://www.dianleida.net"


def load_saved_cookies(context) -> bool:
    """加载已保存的 cookie，成功返回 True"""
    if not COOKIE_FILE.exists():
        return False
    try:
        with open(COOKIE_FILE, "r", encoding="utf-8") as f:
            cookies = json.load(f)
        context.add_cookies(cookies)
        print(f"[[OK]] 已加载 {len(cookies)} 个 cookie")
        return True
    except Exception as e:
        print(f"[!] cookie 加载失败: {e}")
        return False


def save_cookies(context):
    """保存当前 cookie 到文件"""
    cookies = context.cookies()
    with open(COOKIE_FILE, "w", encoding="utf-8") as f:
        json.dump(cookies, f, ensure_ascii=False, indent=2)
    print(f"[[OK]] cookie 已保存 ({len(cookies)} 个) -> {COOKIE_FILE}")


def is_logged_in(page) -> bool:
    """检测是否已登录"""
    try:
        body = page.text_content("body") or ""
        # 登录后的页面特征
        keywords = ["工作台", "退出", "我的关注", "选品库", "logout", "dashboard"]
        for kw in keywords:
            if kw.lower() in body.lower():
                return True
    except Exception:
        pass
    try:
        url = page.url
        if "/1688/" in url or "/buy/" in url:
            return True
    except Exception:
        pass
    return False


def do_login(page, context):
    """执行登录操作：点击登录按钮，等待用户手动完成，检测到登录后自动保存 cookie"""
    print("\n[!] 需要登录店雷达")
    print("[!] 浏览器已打开，请手动扫码或账号密码登录")
    print("[!] 登录完成后，脚本会自动检测并保存 cookie\n")

    # 点击登录/注册按钮
    try:
        login_btn = page.get_by_text(re.compile(r"登录", re.IGNORECASE))
        login_btn.first.click(timeout=10000)
        print("[*] 已点击登录按钮，等待登录完成...")
    except Exception as e:
        print(f"[*] 自动点击登录按钮失败 ({e})，请手动在浏览器中登录")

    # 轮询检测登录成功（URL 变化或页面出现登录态元素）
    for i in range(120):  # 最多等 120 秒
        page.wait_for_timeout(1000)
        try:
            url = page.url
            # 检测 URL 是否包含内部路径
            if "/1688/" in url or "/buy/" in url or "/competeShop/" in url:
                print(f"\n[[OK]] 检测到 URL 跳转: {url}")
                save_cookies(context)
                return True
            # 检测页面元素
            body_text = page.text_content("body") or ""
            if "工作台" in body_text or "退出" in body_text:
                print(f"\n[[OK]] 检测到登录态文本")
                save_cookies(context)
                return True
        except Exception:
            pass
        if i % 10 == 0 and i > 0:
            print(f"  等待中... ({i}s)")

    print("\n[!] 登录检测超时，尝试保存当前 cookies")
    save_cookies(context)  # 超时也保存
    return False


def ensure_logged_in(context, page) -> bool:
    """确保已登录，返回登录状态"""
    # 先尝试加载 cookie
    if load_saved_cookies(context):
        page.goto(BASE_URL, wait_until="domcontentloaded")
        page.wait_for_timeout(3000)
        if is_logged_in(page):
            print("[[OK]] Cookie 有效，已登录状态")
            return True
        else:
            print("[!] Cookie 已过期，需要重新登录")

    # 需要手动登录
    page.goto(BASE_URL, wait_until="domcontentloaded")
    page.wait_for_timeout(2000)

    # 处理地区选择弹窗（如果出现）
    try:
        region_text = page.get_by_text("请选择地区")
        if region_text.is_visible(timeout=3000):
            confirm_btn = page.get_by_text("确定", exact=True)
            if confirm_btn.is_visible(timeout=2000):
                confirm_btn.click()
                page.wait_for_timeout(1000)
    except Exception:
        pass

    do_login(page, context)

    # 最后再检查一次
    page.goto(BASE_URL, wait_until="domcontentloaded")
    page.wait_for_timeout(3000)
    if is_logged_in(page):
        save_cookies(context)
        return True
    else:
        # cookies 可能已经由 do_login 保存了
        if COOKIE_FILE.exists():
            print("[OK] cookies.json 已存在，尝试继续")
            return True
        print("[[FAIL]] 登录检测失败，请检查")
        return False


def main():
    with sync_playwright() as p:
        # 启动浏览器 (有头模式，方便手动操作)
        browser = p.chromium.launch(
            headless=False,
            args=["--start-maximized"],
        )
        context = browser.new_context(
            viewport={"width": 1280, "height": 800},
            locale="zh-CN",
            timezone_id="Asia/Shanghai",
        )
        page = context.new_page()

        ok = ensure_logged_in(context, page)
        if ok:
            print("\n[OK] 登录状态正常，准备就绪")
            print(f"[*] 当前页面: {page.title()}")
            # 进入选品库页面，方便后续抓包
            page.goto("https://www.dianleida.net/1688/competeShop/category/library/", wait_until="domcontentloaded")
            page.wait_for_timeout(3000)
            print(f"[*] 已进入选品库: {page.title()}")
        else:
            print("\n[FAIL] 登录失败")
            sys.exit(1)

        print("\n[指令] 浏览器保持打开，你可以:")
        print("  1. 打开开发者工具 (F12) -> Network 标签")
        print("  2. 在页面上操作（搜索商品、查看榜单等）")
        print("  3. 观察 Network 中的 API 请求")
        print("  按 Ctrl+C 关闭浏览器退出\n")
        try:
            page.wait_for_timeout(999999999)  # 保持打开，等待用户探索
        except (KeyboardInterrupt, Exception):
            pass
        finally:
            browser.close()


if __name__ == "__main__":
    main()
