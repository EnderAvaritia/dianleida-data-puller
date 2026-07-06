"""
批量采集商家：按类目拆分，绕过免费版 100 条/次限制
=================================================

原理：API 支持 categoryIdList 参数按行业过滤。免费版虽然限制每次查询只能拿约 100 条，
但不同类目返回的是不同的商家集合。遍历 52 个一级类目分别搜索，合并去重后能得到更多数据。

用法：
  # 采集常州所有商家
  python fetch_all_shops.py --province 江苏 --city 常州

  # 采集杭州所有商家
  python fetch_all_shops.py --province 浙江 --city 杭州

  # 断点续传（自动从上次中断的类目继续）
  python fetch_all_shops.py --province 江苏 --city 常州 --resume

  # 手动指定起始类目
  python fetch_all_shops.py --province 江苏 --city 常州 --from 10
"""
import csv
import json
import sys
import time
from datetime import datetime
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")

from playwright.sync_api import sync_playwright

COOKIE_FILE = Path("cookies.json")
OUTPUT_DIR = Path("output")
OUTPUT_DIR.mkdir(exist_ok=True)

FACTORY_URL = "https://www.dianleida.net/1688/competeShop/category/shopList/shopLibrary/"
CAT_API_URL = "https://api.dianleida.net/dld/api/selectAnalyze/getCategoryList"
SHOP_API_URL = "https://api.dianleida.net/dld/api/shopSearch/queryList"


# ── 断点续传 ─────────────────────────────────────

def _checkpoint_path(province="", city=""):
    """checkpoint 文件路径，用于自动断点续传"""
    name = f"shops_{province or '全国'}{city or ''}_all"
    return OUTPUT_DIR / f".{name}.checkpoint"


def _save_checkpoint(province, city, from_idx, total_items, total_cats):
    """保存断点，记录已完成的类目索引"""
    data = {
        "province": province,
        "city": city,
        "from_idx": from_idx,
        "total_items": total_items,
        "total_cats": total_cats,
        "timestamp": datetime.now().isoformat(),
    }
    path = _checkpoint_path(province, city)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def _load_checkpoint(province="", city=""):
    """读取断点，不存在返回 None"""
    path = _checkpoint_path(province, city)
    if path.exists():
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    return None


def _clear_checkpoint(province="", city=""):
    path = _checkpoint_path(province, city)
    if path.exists():
        path.unlink()


def get_categories() -> list[dict]:
    """
    获取所有一级类目列表。
    返回 [{"id": "67", "name": "办公、文化"}, ...]
    """
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        ctx = browser.new_context(locale="zh-CN")
        with open(COOKIE_FILE, encoding="utf-8") as f:
            ctx.add_cookies(json.load(f))
        page = ctx.new_page()

        cat_data = []

        def on_resp(resp):
            if "getCategoryList" in resp.url:
                try:
                    d = resp.json()
                    if d.get("code") == 200:
                        cat_data.extend(d.get("result", []))
                except:
                    pass

        page.on("response", on_resp)
        page.goto(FACTORY_URL, wait_until="domcontentloaded", timeout=30000)
        page.wait_for_timeout(3000)

        # 关弹窗
        page.evaluate("""() => {
            document.querySelectorAll('div[class="pop"]').forEach(e => {
                for (let a of e.getAttributeNames()) { if (a.startsWith("data-v-")) { e.remove(); break; } }
            });
            document.querySelectorAll(".el-dialog__wrapper, .v-modal").forEach(e => e.remove());
        }""")
        page.wait_for_timeout(1000)

        # 点击"选择类目"触发 API
        btn = page.locator(".select-category").first
        if btn.is_visible():
            btn.click()
            page.wait_for_timeout(5000)

        browser.close()

    result = []
    for cat in cat_data:
        cid = cat.get("category_id", "")
        name = cat.get("category_chinese_name") or cat.get("category_name", "")
        if cid:
            result.append({"id": cid, "name": name})
    return result


def search_shops(province: str, city: str, category_id: str) -> list[dict]:
    """
    按地区和类目搜索商家。
    返回商家列表，每项包含 shopId, company, province, city, isFactory 等字段。
    """
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        ctx = browser.new_context(locale="zh-CN")
        with open(COOKIE_FILE, encoding="utf-8") as f:
            ctx.add_cookies(json.load(f))
        page = ctx.new_page()

        all_items = []
        api_responses = []

        def handle_route(route):
            req = route.request
            if SHOP_API_URL in req.url:
                body = json.loads(req.post_data or "{}")
                # 注入地区和类目过滤
                loc_entry = {"province": province} if province else {}
                if city:
                    loc_entry["city"] = [city]
                body["query"]["location"] = [loc_entry] if loc_entry else []
                body["query"]["categoryIdList"] = [category_id] if category_id else []
                body["pageSize"] = 100
                body["sortField"] = "bookedCount30d"
                route.continue_(post_data=json.dumps(body, ensure_ascii=False))
            else:
                route.continue_()

        def on_response(resp):
            if SHOP_API_URL in resp.url:
                try:
                    api_responses.append(resp)
                except:
                    pass

        page.on("response", on_response)
        page.route("**/dld/api/shopSearch/queryList", handle_route)
        page.goto(FACTORY_URL, wait_until="domcontentloaded", timeout=30000)
        page.wait_for_timeout(5000)

        # 关弹窗
        for _ in range(3):
            page.evaluate("""() => {
                document.querySelectorAll('div[class="pop"]').forEach(e => {
                    for (let a of e.getAttributeNames()) { if (a.startsWith("data-v-")) { e.remove(); break; } }
                });
                document.querySelectorAll(".el-dialog__wrapper, .v-modal").forEach(e => e.remove());
                document.body.style.overflow = 'auto';
                document.documentElement.style.overflow = 'auto';
            }""")
            page.wait_for_timeout(1500)

        # 提取第一页
        for resp in api_responses:
            try:
                d = resp.json()
                if d.get("code") == 200:
                    items = d.get("result", {}).get("list", [])
                    all_items.extend(items)
                    break
            except:
                pass

        # 翻页
        api_responses.clear()
        while True:
            try:
                btn = page.locator("button.btn-next").first
                if not btn.is_visible(timeout=2000) or btn.is_disabled():
                    break
                btn.click(force=True, timeout=5000)
                page.wait_for_timeout(2500)
                for resp in api_responses:
                    try:
                        d = resp.json()
                        if d.get("code") == 200:
                            items = d.get("result", {}).get("list", [])
                            if items:
                                all_items.extend(items)
                            break
                    except:
                        pass
                if len(api_responses) > 0:
                    break
            except:
                break

        browser.close()
    return all_items


def save_results(items: list[dict], file_prefix: str):
    """保存结果到 JSON 和 CSV"""
    json_path = OUTPUT_DIR / f"{file_prefix}.json"
    csv_path = OUTPUT_DIR / f"{file_prefix}.csv"

    # JSON
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump({"total": len(items), "items": items}, f, ensure_ascii=False, indent=2)

    # CSV
    fields = ["shopId", "company", "sellerAccount", "province", "city", "address",
              "isFactory", "tpYear", "dayBookedCount", "daySalesVolume",
              "repeatRate", "wwResponseRate", "bookedCount30d", "saleQuantity30d",
              "salesVolume30d", "offerCount", "beFavedCount", "employeesCount",
              "factorySize", "productionService", "domainUri"]
    with open(csv_path, "w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        for item in items:
            w.writerow({k: item.get(k, "") for k in fields})

    # 统计
    factory_cnt = sum(1 for s in items if s.get("isFactory") == True)
    print(f"\n{'='*50}")
    print(f"结果: {len(items)} 家")
    print(f"工厂: {factory_cnt} 家 ({factory_cnt/len(items)*100:.1f}%)")
    print(f"JSON: {json_path}")
    print(f"CSV:  {csv_path}")


def main():
    import argparse

    parser = argparse.ArgumentParser(
        description="按类目批量采集商家，绕过免费版 100 条限制",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例:
  python fetch_all_shops.py --province 江苏 --city 常州
  python fetch_all_shops.py --province 浙江 --city 杭州 --from 10
  python fetch_all_shops.py --province 广东 --city 深圳 --resume
  python fetch_all_shops.py --province 广东 --city 深圳 --max-cats 5
        """,
    )
    parser.add_argument("--province", default="", help="省份")
    parser.add_argument("--city", default="", help="城市")
    parser.add_argument("--from", dest="from_idx", type=int, default=0, help="从第几个类目开始（手动断点续传）")
    parser.add_argument("--resume", action="store_true", help="自动断点续传，从上次中断的类目继续")
    parser.add_argument("--max-cats", type=int, default=0, help="最多处理多少个类目 (0=全部)")

    args = parser.parse_args()

    # 1. 断点续传：优先 --resume 自动恢复，其次 --from 手动指定
    if args.resume and args.from_idx == 0:
        cp = _load_checkpoint(args.province, args.city)
        if cp:
            args.from_idx = cp["from_idx"]
            print(f"[断点续传] 从第 {cp['from_idx']} 个类目继续 (已有 {cp['total_items']} 条数据)")
        else:
            print("[WARN] 未找到断点，从头开始")

    # 2. 获取类目列表
    print("正在获取类目列表...")
    cats = get_categories()
    print(f"获取到 {len(cats)} 个一级类目")

    # 保存类目列表
    with open(OUTPUT_DIR / "categories.json", "w", encoding="utf-8") as f:
        json.dump(cats, f, ensure_ascii=False, indent=2)

    # 2. 逐个类目搜索
    selected = cats[args.from_idx:]
    if args.max_cats > 0:
        selected = selected[: args.max_cats]

    all_items = []
    seen = set()

    # 尝试加载已有数据（断点续传）
    output_name = f"shops_{args.province or '全国'}{args.city or ''}"
    resume_path = OUTPUT_DIR / f"{output_name}.json"
    if resume_path.exists() and args.from_idx > 0:
        try:
            existing = json.loads(resume_path.read_text(encoding="utf-8"))
            for item in existing.get("items", []):
                sid = item.get("shopId") or item.get("company", "")
                if sid not in seen:
                    seen.add(sid)
                    all_items.append(item)
            print(f"已加载 {len(all_items)} 条已有数据")
        except:
            pass

    for idx, cat in enumerate(selected):
        cid = cat["id"]
        name = cat["name"]
        global_idx = args.from_idx + idx + 1
        total = len(cats)

        print(f"[{global_idx}/{total}] [{cid}] {name} ...", end=" ", flush=True)
        try:
            items = search_shops(args.province, args.city, cid)
            new_count = 0
            for item in items:
                sid = item.get("shopId") or item.get("company", "")
                if sid not in seen:
                    seen.add(sid)
                    all_items.append(item)
                    new_count += 1
            print(f"{len(items)} 条, 新增 {new_count}, 累计 {len(all_items)}")
        except Exception as e:
            print(f"[FAIL] {e}")

        # 每个类目处理完都保存 checkpoint（用于自动断点续传）
        _save_checkpoint(args.province, args.city, global_idx, len(all_items), total)

        # 每 10 个类目保存一次完整结果（用于手动断点续传 --from）
        if (global_idx) % 10 == 0:
            save_results(all_items, f"{output_name}_checkpoint")
            print(f"  -> 已保存 checkpoint")

    # 3. 最终输出
    save_results(all_items, output_name)
    _clear_checkpoint(args.province, args.city)
    print("全部完成，已清除断点")


if __name__ == "__main__":
    main()
