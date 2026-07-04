"""
调试翻页：拦截 API 请求，看 body 内容
"""
import json
from playwright.sync_api import sync_playwright

FACTORY_URL = "https://www.dianleida.net/1688/competeShop/category/shopList/shopLibrary/"
API_URL = "https://api.dianleida.net/dld/api/shopSearch/queryList"

with sync_playwright() as p:
    browser = p.chromium.launch(headless=False)
    ctx = browser.new_context(
        viewport={"width": 1400, "height": 900}, locale="zh-CN",
        user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/125.0.0.0 Safari/537.36",
    )
    with open("cookies.json") as f:
        ctx.add_cookies(json.load(f))
    page = ctx.new_page()

    # 监听所有 API 请求
    requests_caught = []

    def on_request(req):
        if API_URL in req.url:
            try:
                body = req.post_data
                requests_caught.append(("REQ", len(requests_caught), body[:500]))
                print(f"\n>>> API 请求 #{len(requests_caught)}:")
                print(f"    Method: {req.method}")
                print(f"    Body: {body[:300]}")
            except Exception as e:
                print(f"    Body 读取失败: {e}")

    def on_response(resp):
        if API_URL in resp.url:
            try:
                j = resp.json()
                code = j.get("code")
                total = j.get("result", {}).get("totalCount", 0)
                items = len(j.get("result", {}).get("list", []))
                print(f"<<< API 响应 #{len(requests_caught)}: code={code}, totalCount={total}, items={items}")
            except Exception as e:
                print(f"<<< API 响应 (解析失败): {e}")

    page.on("request", on_request)
    page.on("response", on_response)

    # 路由拦截（模拟代码中的行为）
    province = "浙江"
    city = "杭州"
    page_size = 100

    def handle_route(route):
        req = route.request
        if API_URL in req.url:
            try:
                body = json.loads(req.post_data or "{}")
                print(f"\n  [Route] 原始 body: page={body.get('page')}, pageSize={body.get('pageSize')}, sortField={body.get('sortField')}")
                loc_entry = {"province": province} if province else {}
                if city:
                    loc_entry["city"] = [city]
                body["query"]["location"] = [loc_entry] if loc_entry else []
                body["pageSize"] = page_size
                print(f"  [Route] 修改后 page={body.get('page')}, pageSize={body.get('pageSize')}")
                route.continue_(post_data=json.dumps(body, ensure_ascii=False))
            except Exception as e:
                print(f"  [Route] 错误: {e}")
                route.continue_()
        else:
            route.continue_()

    page.route(f"**/dld/api/shopSearch/queryList", handle_route)

    page.goto(FACTORY_URL, wait_until="domcontentloaded", timeout=30000)
    page.wait_for_timeout(5000)

    print("\n" + "=" * 60)
    print("第 1 页已加载，接下来点击「下一页」")
    print("=" * 60)

    btn = page.locator("button.btn-next")
    print(f"\n下一页按钮: 可见={btn.is_visible()}, 禁用={btn.is_disabled()}")

    # 点击下一页
    btn.click(force=True, timeout=5000)
    page.wait_for_timeout(5000)

    print("\n" + "=" * 60)
    print("点击后 5 秒")
    print("=" * 60)

    input("\n按 Enter 关闭浏览器...")
    browser.close()
