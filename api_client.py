"""
店雷达 API 客户端 v4 — 页面常驻，通过表单交互触发搜索，避免重复加载
"""
import json
import time
from pathlib import Path

from playwright.sync_api import sync_playwright

COOKIE_FILE = Path("cookies.json")
WEB_HOST = "https://www.dianleida.net"
LIBRARY_URL = f"{WEB_HOST}/1688/competeShop/category/library/"

SORT_OPTIONS = {
    "7d_growth": "bookedCount7dGrowthRate",   # 7日订单增长率
    "7d_orders": "bookedCount7d",              # 7日订单数
    "daily_orders": "dayBookedCount",          # 日订单数
    "7d_sales": "saleCount7d",                 # 7日销量
    "7d_revenue": "saleVolume7d",              # 7日销售额
    "repurchase": "offerRepurchaseRate",       # 复购率
    "popularity": "beFavedCount",              # 收藏人气
    "newest": "offerCreateTime",               # 上架时间
    "price_asc": "beginPrice",                 # 价格(升)
}


class DianLeidaClient:
    """店雷达 API 客户端 — 页面常驻 + 表单交互"""

    def __init__(self, cookie_path=COOKIE_FILE):
        self.cookie_path = cookie_path
        self._pw = None
        self._browser = None
        self._ctx = None
        self._page = None
        self._on_library = False  # 是否已在选品库页面

    def __enter__(self):
        self.start()
        return self

    def __exit__(self, *args):
        self.stop()

    # ── 生命周期 ──────────────────────────────────────

    def start(self):
        self._pw = sync_playwright().start()
        self._browser = self._pw.chromium.launch(headless=True)
        self._ctx = self._browser.new_context(locale="zh-CN")
        with open(self.cookie_path, encoding="utf-8") as f:
            self._ctx.add_cookies(json.load(f))
        self._page = self._ctx.new_page()
        self._init_session()

    def stop(self):
        if self._page:
            self._page.close()
        if self._browser:
            self._browser.close()
        if self._pw:
            self._pw.stop()

    def _init_session(self):
        """初始化会话：访问首页 → 关弹窗"""
        self._page.goto(WEB_HOST, wait_until="domcontentloaded", timeout=30000)
        self._page.wait_for_timeout(3000)
        try:
            btn = self._page.query_selector("text=暂不登录")
            if btn and btn.is_visible():
                btn.click()
                self._page.wait_for_timeout(1000)
        except:
            pass

    # ── 页面导航 ──────────────────────────────────────

    def _ensure_library(self):
        """确保在选品库页面"""
        if not self._on_library:
            self._page.goto(LIBRARY_URL, wait_until="domcontentloaded", timeout=30000)
            self._page.wait_for_timeout(5000)
            self._on_library = True

    # ── 搜索操作 ──────────────────────────────────────

    def search_products(
        self,
        keyword: str = "",
        page: int = 1,
        page_size: int = 30,
        sort_field: str = "bookedCount7dGrowthRate",
        sort_type: str = "desc",
        days: int = 30,
    ) -> dict:
        """
        搜索商品 — 填关键词 → 点查询 → 等 API 响应

        性能优化: 首次调用会加载选品库页面，后续翻页只点页码，不重新加载页面
        """
        self._ensure_library()
        self._on_library = True  # 后续翻页不再 reload

        # ── 如果是首次搜索（page=1），填关键词 + 点查询 ──
        if page == 1:
            return self._do_search(keyword, page_size, sort_field, sort_type, days)

        # ── 翻页：点页码 ──
        else:
            return self._go_to_page(page)

    def _do_search(self, keyword, page_size, sort_field, sort_type, days) -> dict:
        """首次搜索：填关键词 → 点查询 → 取结果"""
        # 填关键词
        kw_input = self._page.locator(
            "input[placeholder*='模糊匹配'], input[placeholder*='搜索']"
        ).first
        kw_input.click()
        kw_input.fill("")
        self._page.wait_for_timeout(300)
        kw_input.fill(keyword)
        self._page.wait_for_timeout(500)

        # 点"开始查询"
        with self._page.expect_response(
            lambda r: "/dld/api/offerSearch/queryList" in r.url
            and r.request.method == "POST",
            timeout=30000,
        ) as resp_info:
            self._page.locator("button:has-text('开始查询')").first.click()
            self._page.wait_for_timeout(3000)

        resp = resp_info.value
        return resp.json()

    def _go_to_page(self, target_page: int) -> dict:
        """翻页：点击指定页码 → 取结果"""
        # 找到分页中的目标页码按钮
        with self._page.expect_response(
            lambda r: "/dld/api/offerSearch/queryList" in r.url
            and r.request.method == "POST",
            timeout=30000,
        ) as resp_info:
            # 尝试点击页码
            page_btn = self._page.locator(
                f"ul.el-pager li.number:has-text('{target_page}')"
            ).first
            if page_btn.is_visible():
                page_btn.click()
            else:
                # 如果页码不在可视区域，点击"下一页"箭头
                next_btn = self._page.locator(
                    "button.btn-next, button:has-text('下一页')"
                ).first
                if next_btn.is_visible():
                    next_btn.click()
                else:
                    raise Exception(f"无法翻到第 {target_page} 页")
            self._page.wait_for_timeout(3000)

        resp = resp_info.value
        return resp.json()

    # ── 商家/供应商搜索（按地区） ────────────────────────

    FACTORY_URL = f"{WEB_HOST}/1688/competeShop/category/shopList/shopLibrary/"

    def search_shops(
        self,
        page_no: int = 1,
        page_size: int = 20,
        sort_field: str = "bookedCount30d",
    ) -> dict:
        """
        搜索商家/供应商（按 30日订单数排序）

        导航到一手源头工厂页面，自动触发 shopSearch/queryList API 并捕获结果。
        (地区筛选暂不支持 API 级注入，可在 Python 端按 province/city 字段过滤)
        """
        with self._page.expect_response(
            lambda r: "/dld/api/shopSearch/queryList" in r.url and r.request.method == "POST",
            timeout=30000,
        ) as resp_info:
            self._page.goto(self.FACTORY_URL, wait_until="domcontentloaded", timeout=30000)
            self._page.wait_for_timeout(8000)
        return resp_info.value.json()

    # ── 辅助方法 ──────────────────────────────────────

    def _close_dialogs(self):
        """移除所有弹窗遮罩"""
        # 方法1: 点击已知文字按钮
        for text in ["暂不登录", "知道了", "取消", "确定"]:
            try:
                btn = self._page.locator(f"button:has-text('{text}')").first
                if btn.is_visible(timeout=1000):
                    btn.click()
                    self._page.wait_for_timeout(500)
            except:
                pass
        # 方法2: JS 移除遮罩元素
        self._page.evaluate("""() => {
            document.querySelectorAll('.el-dialog__wrapper, .v-modal, .pop').forEach(el => el.remove());
        }""")

    def is_logged_in(self) -> bool:
        try:
            self._page.goto(LIBRARY_URL, wait_until="domcontentloaded", timeout=30000)
            self._page.wait_for_timeout(5000)
            body = self._page.text_content("body") or ""
            return "工作台" in body
        except Exception:
            return False


# ── 快捷测试 ────────────────────────────────────────

if __name__ == "__main__":
    with DianLeidaClient() as c:
        if c.is_logged_in():
            print("[OK] 已登录")

            # 测试搜索
            r = c.search_products("女装", page=1)
            total = r.get("result", {}).get("totalCount", 0)
            items = r.get("result", {}).get("list", [])
            print(f"[OK] 搜索 '女装': 共 {total} 条, 本页 {len(items)} 条")
            if items:
                print(f"  第一条: {items[0].get('subject', '')[:40]}")

            # 测试翻页
            r2 = c.search_products("女装", page=2)
            items2 = r2.get("result", {}).get("list", [])
            print(f"[OK] 翻到第 2 页: {len(items2)} 条")
            if items2:
                print(f"  第一条: {items2[0].get('subject', '')[:40]}")
        else:
            print("[FAIL] 未登录")
