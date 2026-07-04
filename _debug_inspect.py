"""
详细检查页面元素，模拟 _close_dialogs 过程
"""
import json
from playwright.sync_api import sync_playwright

FACTORY_URL = "https://www.dianleida.net/1688/competeShop/category/shopList/shopLibrary/"

with sync_playwright() as p:
    browser = p.chromium.launch(headless=False)
    ctx = browser.new_context(
        viewport={"width": 1400, "height": 900},
        locale="zh-CN",
        user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/125.0.0.0 Safari/537.36",
    )
    with open("cookies.json") as f:
        ctx.add_cookies(json.load(f))
    page = ctx.new_page()

    page.goto(FACTORY_URL, wait_until="domcontentloaded", timeout=30000)
    page.wait_for_timeout(5000)

    print("=== 当前页面 URL ===")
    print(page.url)

    print("\n=== 所有 span.curp 文本 ===")
    spans = page.locator("span.curp")
    for i in range(spans.count()):
        txt = spans.nth(i).inner_text()
        print(f"  [{i}] {repr(txt)}")

    print("\n=== 所有 div[class=\"pop\"] ===")
    pops = page.locator('div[class="pop"]')
    print(f"  数量: {pops.count()}")
    for i in range(pops.count()):
        txt = pops.nth(i).inner_text()[:300]
        html = pops.nth(i).inner_html()[:500]
        attrs = page.evaluate(
            """(i) => {
                let els = document.querySelectorAll('div[class="pop"]');
                if (!els[i]) return [];
                return [...els[i].getAttributeNames()].map(n => n + '=' + els[i].getAttribute(n));
            }""",
            i,
        )
        print(f"  [{i}] 属性: {attrs}")
        print(f"  [{i}] 文本: {repr(txt)}")
        print(f"  [{i}] HTML: {repr(html)}")

    print("\n=== 所有 .el-dialog__headerbtn ===")
    hdrs = page.locator(".el-dialog__headerbtn")
    print(f"  数量: {hdrs.count()}")
    for i in range(hdrs.count()):
        vis = hdrs.nth(i).is_visible(timeout=200)
        print(f"  [{i}] 可见: {vis}")

    print("\n=== 所有 .el-icon-close ===")
    cls = page.locator(".el-icon-close")
    print(f"  数量: {cls.count()}")
    for i in range(min(10, cls.count())):
        vis = cls.nth(i).is_visible(timeout=200)
        txt = cls.nth(i).inner_text()[:50]
        print(f"  [{i}] 可见={vis} text={repr(txt)}")

    print("\n=== 所有 .el-message-box__headerbtn ===")
    msg = page.locator(".el-message-box__headerbtn")
    print(f"  数量: {msg.count()}")

    # ---- 点击下一页 ----
    print("\n=== 点击下一页... ===")
    before = len(page.locator('div[class="pop"]').all())
    btn = page.locator("button.btn-next").first
    print(f"  下一页可见: {btn.is_visible()}, 禁用: {btn.is_disabled()}")
    btn.click(force=True, timeout=5000)
    page.wait_for_timeout(3000)

    print("\n=== 点击后页面 ===")
    print(f"  URL: {page.url}")

    pops2 = page.locator('div[class="pop"]')
    if pops2.count() > 0:
        print(f"  .pop 数量: {pops2.count()}")
        for i in range(pops2.count()):
            txt = pops2.nth(i).inner_text()[:500]
            html = pops2.nth(i).inner_html()[:800]
            attrs = page.evaluate(
                """(i) => {
                    let els = document.querySelectorAll('div[class="pop"]');
                    if (!els[i]) return [];
                    return [...els[i].getAttributeNames()].map(n => n + '=' + els[i].getAttribute(n));
                }""",
                i,
            )
            print(f"  [{i}] 属性: {attrs}")
            print(f"  [{i}] 文本: {repr(txt)}")
            print(f"  [{i}] HTML: {repr(html)}")
    else:
        print("  没有 .pop")

    # 检查是否弹窗内容包含"升级套餐"
    body_text = page.inner_text("body")
    if "升级套餐" in body_text:
        print("\n  页面包含「升级套餐」文本 ✓")

    print("\n浏览器已打开，请手动查看页面状态。")
    print("按 Enter 关闭...")
    input()
    browser.close()
