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
from datetime import datetime
from pathlib import Path

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

from api_client import DianLeidaClient

OUTPUT_DIR = Path("output")
OUTPUT_DIR.mkdir(exist_ok=True)


# ── 断点续传 ─────────────────────────────────────

def _checkpoint_path(province="", city=""):
    name = f"shops_{province}{city}" if province else "shops"
    return OUTPUT_DIR / f".{name}.checkpoint"


def _save_checkpoint(province, city, page, total_items, total_count):
    """保存断点，用于失败后恢复"""
    data = {
        "mode": "shop",
        "province": province,
        "city": city,
        "last_page": page,
        "total_items": total_items,
        "total_count": total_count,
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


# ── 商品搜索 ─────────────────────────────────────

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
            print(f"  [FAIL] {e}")
            break

    client.stop()
    _save_products(name, all_items)


# ── 商家搜索 ─────────────────────────────────────

def search_shops(province="", city="", max_pages=0, page_size=100,
                 from_page=1, resume=False, debug=False):
    """
    拉取商家/供应商列表，支持按地区筛选和多页拉取

    支持断点续传: 每翻一页自动保存 checkpoint; --resume 从上次中断处继续。
    """
    # ── 断点续传 ──
    if resume:
        cp = _load_checkpoint(province, city)
        if cp:
            province = cp.get("province", province)
            city = cp.get("city", city)
            from_page = cp["last_page"] + 1
            print(f"[断点续传] 从第 {cp['last_page']} 页继续 (已有 {cp['total_items']} 条)")
            # 加载已有数据
            name = f"shops_{province}{city}" if province else "shops"
            json_path = OUTPUT_DIR / f"{name}.json"
            if json_path.exists():
                with open(json_path, "r", encoding="utf-8") as f:
                    existing = json.load(f)
                existing_items = existing.get("items", [])
                print(f"  已加载 {len(existing_items)} 条已有数据")
            else:
                existing_items = []
        else:
            print("[WARN] 未找到断点，从头开始")
            from_page = 1
            existing_items = []
    else:
        existing_items = []

    client = DianLeidaClient(headless=not debug)
    client.start()
    if not client.is_logged_in():
        print("[FAIL] 未登录")
        client.stop()
        return

    all_items = list(existing_items)

    # on_page callback: 每页回调 → 保存 checkpoint
    def on_page(page_no, items, total_accumulated, total_count):
        _save_checkpoint(province, city, page_no, total_accumulated, total_count)
        return True  # 继续拉取

    try:
        result = client.search_shops(
            province=province, city=city,
            from_page=from_page, page_size=page_size,
            max_pages=max_pages, on_page=on_page,
        )
        new_items = result.get("result", {}).get("list", [])
        # 合并已有数据和新拉取的数据（无重叠，from_page=last_page+1）
        all_items.extend(new_items)
    except Exception as e:
        print(f"  [FAIL] {e}")

    client.stop()

    # 保存
    name = f"shops_{province}{city}" if province else "shops"
    _save_shops(all_items, name)

    # 清除 checkpoint (成功拉取完毕)
    if all_items:
        _clear_checkpoint(province, city)


# ── 保存函数 ─────────────────────────────────────

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


# ── CLI ──────────────────────────────────────────

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
    parser.add_argument("--from-page", type=int, default=1, help="起始页码 (用于跳过已拉取的页)")
    parser.add_argument("--resume", action="store_true", help="断点续传，从上次中断处继续")
    parser.add_argument("--debug", action="store_true", help="打开浏览器窗口 (调试用)")

    args = parser.parse_args()

    if args.mode == "shop":
        if args.city and not args.province:
            print("[FAIL] --city 必须配合 --province 使用，如: --province 江苏 --city 常州")
            sys.exit(1)
        size = args.size if args.size != 30 else 100  # shop 模式默认 100 (API 上限)
        search_shops(
            province=args.province, city=args.city,
            max_pages=args.pages, page_size=size,
            from_page=args.from_page,
            resume=args.resume,
            debug=args.debug,
        )
    else:
        kw = args.keyword or input("输入搜索关键词: ")
        search_products(kw, args.pages, args.size, args.sort, debug=args.debug)
