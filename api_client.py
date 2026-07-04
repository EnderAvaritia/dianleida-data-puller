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

    def __init__(self, cookie_path=COOKIE_FILE, headless=True):
        self.cookie_path = cookie_path
        self._headless = headless
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
        self._browser = self._pw.chromium.launch(headless=self._headless)
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
        from_page: int = 1,
        page_size: int = 100,
        sort_field: str = "bookedCount30d",
        max_pages: int = 0,
        on_page=None,
    ) -> dict:
        """
        搜索商家/供应商，支持按地区筛选和多页拉取（通过点击"下一页"分页）

        通过 route 拦截自动触发的 API 请求并注入 location 参数，实现地区过滤。
        翻页通过 Vue 分页组件的"下一页"按钮触发，保留页面签名逻辑。

        参数:
            province: 省份 (如 "浙江", "广东", "")
            city: 城市 (如 "杭州", "常州", 留空=全省)
            from_page: 起始页码 (用于断点续传)
            page_size: 每页条数 (默认 100, API 上限 100)
            sort_field: 排序字段
            max_pages: 最大页数 (0=所有页)
            on_page: 每页回调 fn(page_no, items, total_accumulated, total_count) -> bool(是否继续)
        """
        all_items = []
        total_count = 0
        api_responses = []

        # Route handler: inject location into API call
        def handle_route(route):
            req = route.request
            if "/dld/api/shopSearch/queryList" in req.url:
                body = json.loads(req.post_data or "{}")
                # 构造 location 参数（city 必须是数组，如 ["杭州"]）
                loc_entry = {"province": province} if province else {}
                if city:
                    loc_entry["city"] = [city]
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

        # Navigate and wait for the first API response
        self._page.goto(self.FACTORY_URL, wait_until="domcontentloaded", timeout=30000)
        try:
            with self._page.expect_response(
                lambda r: "/dld/api/shopSearch/queryList" in r.url and r.request.method == "POST",
                timeout=20000,
            ) as resp_info:
                # Wait for response while dialogs are handled
                pass
            resp = resp_info.value
            try:
                d = resp.json()
                if isinstance(d, dict) and d.get("code") == 200:
                    api_responses.append(resp)
            except Exception:
                pass
        except Exception:
            pass

        # Close dialogs now
        self._close_dialogs()
        self._page.wait_for_timeout(2000)

        # Check if we got page 1 data; if not, reload
        got_data = False
        for resp in list(api_responses):
            try:
                d = resp.json()
                if isinstance(d, dict) and d.get("code") == 200:
                    got_data = True
                    break
            except Exception:
                pass

        if not got_data:
            print("  [!] 首次加载未获取到数据，重新加载...", flush=True)
            self._close_dialogs()
            self._page.wait_for_timeout(1000)
            self._page.goto(self.FACTORY_URL, wait_until="domcontentloaded", timeout=30000)
            self._page.wait_for_timeout(5000)
            self._close_dialogs()
            self._page.wait_for_timeout(3000)

        # Helper: wait for and extract a new API response
        def _wait_response(before_count, timeout=15):
            for _ in range(timeout * 4):
                self._page.wait_for_timeout(250)
                if len(api_responses) > before_count:
                    break
            for resp in api_responses[before_count:]:
                try:
                    d = resp.json()
                    if d.get("code") == 200:
                        return d
                except Exception:
                    pass
            return None

        # Helper: click next page silently, return response data or None
        def _click_next():
            before = len(api_responses)
            for attempt in range(3):
                try:
                    btn = self._page.locator("button.btn-next").first
                    if not btn.is_visible(timeout=1000) or btn.is_disabled():
                        if attempt < 2:
                            self._page.wait_for_timeout(500)
                            self._close_dialogs()
                            continue
                        return None
                    self._close_dialogs()
                    self._page.wait_for_timeout(200)
                    btn.click(force=True, timeout=5000)
                    data = _wait_response(before)
                    if data is not None or attempt >= 2:
                        return data
                    self._page.wait_for_timeout(1000)
                except Exception:
                    if attempt >= 2:
                        return None
                    self._page.wait_for_timeout(1000)
            return None

        # ── Skip pages until from_page ──
        # Page 1 is already loaded above. Skip to from_page if needed.
        collected_page_1 = False
        current_page = 1

        if from_page > 1:
            print(f"  -> 跳过前 {from_page - 1} 页到第 {from_page} 页...", flush=True)
            while current_page < from_page:
                current_page += 1
                data = _click_next()
                if data is None:
                    break
                # Page 1 already captured; now we have page 2, 3, ..., from_page
            if current_page < from_page:
                print(f"  [FAIL] 只能翻到第 {current_page} 页", flush=True)
                return {"code": -1, "result": {"totalCount": 0, "list": []}}
            # Now we're at from_page. Collect this page's data and any additional pages.
            # We need to get the current page data. It was already fetched.
            # The last API response is the current page. Let me re-read it.
            pass

        # ── Collect data from current page onward ──
        # First, extract page 1 (or the from_page we just skipped to) data
        for resp in api_responses[-3:]:
            try:
                data = resp.json()
                if data.get("code") == 200:
                    items = data.get("result", {}).get("list", [])
                    total_count = data.get("result", {}).get("totalCount", 0)
                    if current_page >= from_page:
                        all_items.extend(items)
                        if from_page > 1:
                            print(f"\n[商家搜索] 地区={province} {city} 每页{page_size}条")
                        print(f"  第 {current_page} 页: {len(items)} 条 (累计 {len(all_items)}/{total_count})", flush=True)
                        if on_page and not on_page(current_page, items, len(all_items), total_count):
                            break
                    break
            except Exception:
                pass

        # ── Paginate via clicking "下一页" ──
        while True:
            current_page += 1
            if max_pages > 0 and current_page > max_pages:
                break

            print(f"  -> 第 {current_page} 页...", end="", flush=True)
            new_data = _click_next()
            if new_data is None:
                print(" 无响应", flush=True)
                # 检测是否是免费版限制弹窗
                upgrade = self._page.locator("text=升级套餐").first
                if upgrade.is_visible(timeout=500):
                    print("  [限制] 免费版最多查看 100 条，升级套餐可查看更多", flush=True)
                break

            items = new_data.get("result", {}).get("list", [])
            if not items:
                print(" 无数据", flush=True)
                break

            all_items.extend(items)
            print(f" {len(items)} 条 (累计 {len(all_items)}/{total_count})", flush=True)

            if on_page and not on_page(current_page, items, len(all_items), total_count):
                break

            if not items or len(all_items) >= total_count:
                break

        self._page.unroute("**/dld/api/shopSearch/queryList")
        print(f"  [完成] 共 {len(all_items)} 条 (总计 {total_count})", flush=True)

        return {
            "code": 200,
            "result": {
                "totalCount": total_count,
                "list": all_items,
            },
        }

    # ── 辅助方法 ──────────────────────────────────────

    def _close_dialogs(self):
        """快速移除所有弹窗遮罩"""
        # 检测免费版升级弹窗（包含"升级套餐"文本）
        try:
            upgrade_popup = self._page.locator("text=升级套餐").first
            if upgrade_popup.is_visible(timeout=100):
                # 先找关闭按钮
                close_btn = self._page.locator(".pop .close-btn, .el-dialog__headerbtn, .el-icon-close").first
                if close_btn.is_visible(timeout=200):
                    close_btn.click(force=True, timeout=500)
                    self._page.wait_for_timeout(300)
        except:
            pass
        # 先尝试点击标准 Element UI 弹窗关闭按钮（安全，无副作用）
        for sel in [".el-dialog__headerbtn", ".el-message-box__headerbtn"]:
            try:
                btn = self._page.locator(sel).first
                if btn.is_visible(timeout=200):
                    btn.click(force=True, timeout=500)
                    self._page.wait_for_timeout(200)
            except:
                pass
        # 移除残留元素，恢复滚动（直接用 JS 移除，不点击弹窗内部按钮以免触发意外操作）
        self._page.evaluate("""() => {
            document.body.style.overflow = 'auto';
            document.documentElement.style.overflow = 'auto';
            // 移除带 Vue scoped data-v-* 属性的 .pop 弹窗
            document.querySelectorAll('div[class="pop"]').forEach(el => {
                for (let attr of el.getAttributeNames()) {
                    if (attr.startsWith('data-v-')) { el.remove(); break; }
                }
            });
            // 标准 Element UI 弹窗
            const selectors = [
                '.el-dialog__wrapper', '.v-modal', '.el-overlay',
                '.el-message-box__wrapper', '.el-dialog', '.el-message',
                '.el-notification', '.mask',
            ];
            selectors.forEach(s => {
                try { document.querySelectorAll(s).forEach(el => el.remove()); } catch(e) {}
            });
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
