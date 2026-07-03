"""
店雷达数据拉取工具
支持商品搜索、商家/供应商拉取，导出 JSON + CSV
"""
import argparse
import csv
import io
import json
import sys
import time
from pathlib import Path

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

from api_client import DianLeidaClient

OUTPUT_DIR = Path("output")
OUTPUT_DIR.mkdir(exist_ok=True)


def search_products(keyword, max_pages=1, page_size=30, sort_field="bookedCount7dGrowthRate", debug=False):
    """按关键词搜索商品，翻页，导出 JSON+CSV"""
    client = DianLeidaClient(headless=not debug)
    client.start()
    if not client.is_logged_in():
        print("[FAIL] 未登录，请先运行 login.py")
        client.stop()
        return

    all_items = []
    name = keyword.replace("*", "").strip() or "products"

    print(f"\n[商品搜索] '{keyword}' 排序={sort_field} 共{max_pages}页", flush=True)
    for pg in range(1, max_pages + 1):
        print(f"  第 {pg}/{max_pages} 页...", end="", flush=True)
        try:
            result = client.search_products(keyword=keyword, page=pg, page_size=page_size, sort_field=sort_field)
            items = result.get("result", {}).get("list", [])
            total = result.get("result", {}).get("totalCount", 0)
            all_items.extend(items)
            print(f" {len(items)} 条 (累计 {len(all_items)}/{total})", flush=True)
            if len(items) < page_size:
                break
            time.sleep(0.5)
        except Exception as e:
            print(f"    [FAIL] {e}")
            break

    client.stop()
    _save_products(name, all_items)


def search_shops(province="", city="", max_pages=0, page_size=200, debug=False):
    """拉取商家/供应商列表，支持按地区筛选和多页拉取"""
    client = DianLeidaClient(headless=not debug)
    client.start()
    if not client.is_logged_in():
        print("[FAIL] 未登录")
        client.stop()
        return

    try:
        result = client.search_shops(province=province, city=city, page_size=page_size, max_pages=max_pages)
        items = result.get("result", {}).get("list", [])
    except Exception as e:
        print(f"  [FAIL] {e}")
        items = []

    client.stop()
    name = f"shops_{province}{city}" if province else "shops"
    _save_shops(items, name)


def _save_products(items, name="products"):
    """保存商品数据"""
    json_path = OUTPUT_DIR / f"{name}.json"
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump({"total": len(items), "items": items}, f, ensure_ascii=False, indent=2)
    print(f"\n[OK] JSON: {json_path} ({len(items)} 条)")

    csv_path = OUTPUT_DIR / f"{name}.csv"
    fields = ["offerId", "subject", "price", "consignPrice", "bookedCount", "saleCount",
              "bookedCount7d", "saleQuantity7d", "salesVolume7d",
              "bookedCount30d", "saleQuantity30d", "salesVolume30d",
              "offerRepurchaseRate", "sellerAccount", "company", "province", "city",
              "tpYear", "levelName", "offerCreateTime", "image"]
    with open(csv_path, "w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        for item in items:
            w.writerow({k: item.get(k, "") for k in fields})
    print(f"[OK] CSV: {csv_path}")


def _save_shops(items, name="shops"):
    """保存商家数据"""
    json_path = OUTPUT_DIR / f"{name}.json"
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump({"total": len(items), "items": items}, f, ensure_ascii=False, indent=2)
    print(f"\n[OK] JSON: {json_path} ({len(items)} 家)")

    csv_path = OUTPUT_DIR / f"{name}.csv"
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
    print(f"[OK] CSV: {csv_path}")

    # 按地区汇总
    regions = {}
    for s in items:
        prov = s.get("province", "未知")
        regions[prov] = regions.get(prov, 0) + 1
    print(f"\n按省份分布:")
    for prov, cnt in sorted(regions.items(), key=lambda x: -x[1])[:10]:
        print(f"  {prov}: {cnt} 家")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="店雷达数据拉取工具")
    parser.add_argument("mode", nargs="?", default="product", choices=["product", "shop"],
                        help="product=搜商品  shop=拉商家 (默认 product)")
    parser.add_argument("keyword", nargs="?", default="", help="搜索关键词 (仅 product 模式)")
    parser.add_argument("--pages", type=int, default=1, help="拉取页数 (0=全部)")
    parser.add_argument("--size", type=int, default=30, help="每页条数 (商家模式默认200)")
    parser.add_argument("--sort", default="bookedCount7dGrowthRate", help="排序字段")
    parser.add_argument("--province", default="", help="省份过滤 (仅 shop 模式)")
    parser.add_argument("--city", default="", help="城市过滤 (仅 shop 模式)")
    parser.add_argument("--debug", action="store_true", help="打开浏览器窗口 (调试用)")

    args = parser.parse_args()

    if args.mode == "shop":
        size = args.size if args.size != 30 else 200  # shop 模式默认 200
        search_shops(province=args.province, city=args.city, max_pages=args.pages, page_size=size, debug=args.debug)
    else:
        kw = args.keyword or input("输入搜索关键词: ")
        search_products(kw, args.pages, args.size, args.sort, debug=args.debug)
