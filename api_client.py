"""
店雷达 API 客户端 v3 — 导航到目标页面，通过 wait_for_response 捕获 API 结果
"""
import json
from pathlib import Path

from playwright.sync_api import sync_playwright

COOKIE_FILE = Path("cookies.json")
WEB_HOST = "https://www.dianleida.net"


class DianLeidaClient:
    def __init__(self, cookie_path=COOKIE_FILE):
        self.cookie_path = cookie_path
        self._pw = None
        self._browser = None
        self._ctx = None
        self._page = None

    def __enter__(self):
        self.start()
        return self

    def __exit__(self, *args):
        self.stop()

    def start(self):
        self._pw = sync_playwright().start()
        self._browser = self._pw.chromium.launch(headless=True)
        self._ctx = self._browser.new_context(locale="zh-CN")
        with open(self.cookie_path, encoding="utf-8") as f:
            self._ctx.add_cookies(json.load(f))
        self._page = self._ctx.new_page()
        self._page.goto(WEB_HOST, wait_until="domcontentloaded", timeout=30000)
        self._page.wait_for_timeout(3000)
        try:
            btn = self._page.query_selector("text=暂不登录")
            if btn and btn.is_visible():
                btn.click()
                self._page.wait_for_timeout(1000)
        except:
            pass
        print("[OK] Session initialized")

    def stop(self):
        if self._page:
            self._page.close()
        if self._browser:
            self._browser.close()
        if self._pw:
            self._pw.stop()

    def is_logged_in(self) -> bool:
        try:
            with self._page.expect_response(
                lambda r: "/dld/api/members/getMemberVerObj" in r.url,
                timeout=15000,
            ):
                self._page.goto(
                    "https://www.dianleida.net/1688/competeShop/category/library/",
                    wait_until="domcontentloaded", timeout=30000,
                )
                self._page.wait_for_timeout(5000)
            return True
        except Exception:
            return False

    def search_products(self, keyword="", page=1, page_size=30,
                        sort_field="bookedCount7dGrowthRate", **kw) -> dict:
        """搜索商品 — 通过页面触发 queryList API"""
        url = "https://www.dianleida.net/1688/competeShop/category/library/"
        with self._page.expect_response(
            lambda r: "/dld/api/offerSearch/queryList" in r.url
            and r.request.method == "POST",
            timeout=20000,
        ) as resp_info:
            self._page.goto(url, wait_until="domcontentloaded", timeout=30000)
            self._page.wait_for_timeout(10000)
        return resp_info.value.json()


if __name__ == "__main__":
    with DianLeidaClient() as c:
        if c.is_logged_in():
            print("[OK] 已登录")
            r = c.search_products()
            print(json.dumps(r, ensure_ascii=False, indent=2)[:3000])
        else:
            print("[FAIL] 未登录")
