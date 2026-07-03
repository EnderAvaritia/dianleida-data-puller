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
        province: str = "",
        city: str = "",
        page_no: int = 1,
        page_size: int = 200,
        sort_field: str = "bookedCount30d",
        max_pages: int = 0,
    ) -> dict:
        """
        搜索商家/供应商，支持按地区筛选和多页拉取（通过点击"下一页"分页）

        通过 route 拦截自动触发的 API 请求并注入 location 参数，实现地区过滤。
        翻页通过 Vue 分页组件的"下一页"按钮触发，保留页面签名逻辑。
        使用 page_size=200 减少翻页次数。

        参数:
            province: 省份 (如 "浙江", "广东", "")
            city: 城市 (如 "杭州", "广州", 留空=全省)
            page_no: 起始页码
            page_size: 每页条数 (最大 200)
            sort_field: 排序字段
                bookedCount30d  - 30日订单数 (默认)
                saleQuantity30d - 30日销量
                salesVolume30d  - 30日销售额
            max_pages: 最大页数 (0=所有页)
        """
        all_items = []
        total_count = 0
        api_responses = []

        # Route handler: inject location + pagination into API call
        def handle_route(route):
            req = route.request
            if "/dld/api/shopSearch/queryList" in req.url:
                body = json.loads(req.post_data or "{}")
                loc_entry = {"province": province} if province else {}
                if city:
                    loc_entry["city"] = city
                body["query"]["location"] = [loc_entry] if loc_entry else []
                body["pageSize"] = page_size
                body["sortField"] = sort_field
                route.continue_(post_data=json.dumps(body, ensure_ascii=False))
            else:
                route.continue_()

        # Response handler: collect API data
        def on_response(resp):
            nonlocal total_count
            if "/dld/api/shopSearch/queryList" in resp.url:
                try:
                    api_responses.append(resp)
                except Exception:
                    pass

        self._page.on("response", on_response)
        self._page.route("**/dld/api/shopSearch/queryList", handle_route)

        # Initial load with page_no=1
        self._page.goto(self.FACTORY_URL, wait_until="domcontentloaded", timeout=30000)
        self._page.wait_for_timeout(5000)
        self._close_dialogs()
        self._page.wait_for_timeout(3000)

        # Collect page 1 data
        for resp in api_responses[-3:]:
            try:
                data = resp.json()
                if data.get("code") == 200:
                    items = data.get("result", {}).get("list", [])
                    all_items.extend(items)
                    total_count = data.get("result", {}).get("totalCount", 0)
                    break
            except Exception:
                pass

        # Paginate via clicking "下一页"
        current_page = 1
        while True:
            current_page += 1
            if max_pages > 0 and current_page > max_pages:
                break

            before = len(api_responses)
            try:
                next_btn = self._page.locator("button.btn-next").first
                if not next_btn.is_visible(timeout=2000) or next_btn.is_disabled():
                    break
                next_btn.click(force=True, timeout=5000)
            except Exception:
                break

            # Wait for new API response
            for _ in range(60):
                self._page.wait_for_timeout(250)
                if len(api_responses) > before:
                    break

            # Extract data from the latest response
            new_data = None
            for resp in api_responses[before:]:
                try:
                    d = resp.json()
                    if d.get("code") == 200:
                        new_data = d
                        break
                except Exception:
                    pass

            if new_data is None:
                break

            items = new_data.get("result", {}).get("list", [])
            all_items.extend(items)
            if not items or len(items) < page_size:
                break

        self._page.unroute("**/dld/api/shopSearch/queryList")

        return {
            "code": 200,
            "result": {
                "totalCount": total_count,
                "list": all_items,
            },
        }

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
