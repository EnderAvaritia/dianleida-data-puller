"""
快速截图：打开商家搜索页面，截取当前状态
"""
import json
from playwright.sync_api import sync_playwright

FACTORY_URL = "https://www.dianleida.net/1688/competeShop/category/shopList/shopLibrary/"
API_URL = "https://api.dianleida.net/dld/api/shopSearch/queryList"

LOCATION = json.dumps([{"province": "浙江", "city": ["杭州"]}], ensure_ascii=False)

with sync_playwright() as p:
    browser = p.chromium.launch(headless=False)
    ctx = browser.new_context(
        viewport={"width": 1400, "height": 900},
        locale="zh-CN",
        user_agent=(
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/125.0.0.0 Safari/537.36"
        ),
    )
    # 加载 Cookie
    with open("cookies.json", "r") as f:
        cookies = json.load(f)
    ctx.add_cookies(cookies)

    page = ctx.new_page()
    responses = []

    def on_response(resp):
        if API_URL in resp.url:
            try:
                responses.append(resp)
            except:
                pass

    page.on("response", on_response)

    # 打开页面
    page.goto(FACTORY_URL, wait_until="domcontentloaded", timeout=30000)
    page.wait_for_timeout(5000)

    # 修改地区和筛选条件
    page.evaluate("""(loc) => {
        document.body.style.overflow = 'auto';
        document.documentElement.style.overflow = 'auto';
    }""")
    page.wait_for_timeout(1000)

    # 截图 - 当前页面
    page.screenshot(path="output/debug_page1_before.png", full_page=False)
    print(f"[OK] 截图: output/debug_page1_before.png")
    print(f"  URL: {page.url}")
    print(f"  API 响应数: {len(responses)}")
    if responses:
        try:
            d = responses[-1].json()
            print(f"  API: code={d.get('code')}, totalCount={d.get('result',{}).get('totalCount',0)}, items={len(d.get('result',{}).get('list',[]))}")
        except:
            print(f"  API: 解析失败")

    # 找"下一页"按钮
    next_btn = page.locator("button.btn-next")
    print(f"  下一页按钮可见: {next_btn.is_visible(timeout=1000)}")
    print(f"  下一页按钮禁用: {next_btn.is_disabled()}")

    # 点击下一页
    before = len(responses)
    next_btn.click(force=True, timeout=5000)
    page.wait_for_timeout(2000)

    # 截图 - 点击下一页后
    page.screenshot(path="output/debug_page2_after.png", full_page=False)
    print(f"\n[OK] 截图: output/debug_page2_after.png")
    print(f"  API 新响应: {len(responses) - before}")
    if len(responses) > before:
        try:
            d = responses[-1].json()
            print(f"  API: code={d.get('code')}, totalCount={d.get('result',{}).get('totalCount',0)}, items={len(d.get('result',{}).get('list',[]))}")
        except:
            print(f"  API: 解析失败")

    # 看看弹窗
    pop = page.locator('div[class="pop"]')
    print(f"  .pop 弹窗: {pop.count()} 个")
    if pop.count() > 0:
        print(f"  弹窗内容: {pop.first.inner_text()[:200]}")

    upgrade = page.locator("text=升级套餐")
    print(f"  升级套餐: {'可见' if upgrade.is_visible(timeout=500) else '不可见'}")

    input("按 Enter 关闭浏览器...")
    browser.close()
