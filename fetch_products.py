"""
店雷达数据拉取 Demo
展示如何使用 api_client 搜索商品并将结果导出为 JSON/CSV
"""
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


def search_to_file(
    keyword: str,
    max_pages: int = 1,
    page_size: int = 30,
    sort_field: str = "bookedCount7dGrowthRate",
    output_name: str = None,
):
    """
    按关键词搜索商品，翻页拉取，保存为 JSON 和 CSV

    参数:
        keyword: 搜索关键词
        max_pages: 最多拉取多少页
        page_size: 每页条数 (最大200)
        sort_field: 排序字段
        output_name: 输出文件名 (不含扩展名)
    """
    client = DianLeidaClient()
    client.start()

    if not client.is_logged_in():
        print("[FAIL] 未登录，请先运行 login.py")
        client.stop()
        return

    all_items = []
    output_name = output_name or keyword.replace("*", "").strip() or "products"

    print(f"\n[开始] 搜索 '{keyword}' 排序={sort_field} 共{max_pages}页")
    for page in range(1, max_pages + 1):
        print(f"  [翻页] 第 {page}/{max_pages} 页...")
        try:
            result = client.search_products(
                keyword=keyword,
                page=page,
                page_size=page_size,
                sort_field=sort_field,
            )
            if result.get("code") != 200:
                print(f"    [FAIL] API 返回异常: {result.get('msg')}")
                break

            items = result.get("result", {}).get("list", [])
            total = result.get("result", {}).get("totalCount", 0)
            all_items.extend(items)
            print(f"    [OK] 本页 {len(items)} 条 (累计 {len(all_items)}/{total})")

            if len(items) < page_size:
                print("    [结束] 已到最后一页")
                break

            time.sleep(0.5)  # 礼貌间隔

        except Exception as e:
            print(f"    [FAIL] 请求失败: {e}")
            break

    client.stop()

    if not all_items:
        print("[FAIL] 没有拉到数据")
        return

    # 保存 JSON
    json_path = OUTPUT_DIR / f"{output_name}.json"
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(
            {"keyword": keyword, "total": len(all_items), "items": all_items},
            f,
            ensure_ascii=False,
            indent=2,
        )
    print(f"\n[OK] JSON 已保存: {json_path} ({len(all_items)} 条)")

    # 保存 CSV（展平核心字段）
    csv_path = OUTPUT_DIR / f"{output_name}.csv"
    fieldnames = [
        "offerId", "subject", "price", "consignPrice",
        "bookedCount", "saleCount", "dayBookedCount", "daySaleQuantity",
        "bookedCount7d", "saleQuantity7d", "salesVolume7d",
        "bookedCount30d", "saleQuantity30d", "salesVolume30d",
        "offerRepurchaseRate", "sellerAccount", "company",
        "province", "city", "tpYear", "levelName",
        "offerCreateTime", "deliveryTime", "image",
    ]
    with open(csv_path, "w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for item in all_items:
            row = {k: item.get(k, "") for k in fieldnames}
            writer.writerow(row)
    print(f"[OK] CSV 已保存: {csv_path}")

    # 打印前几条预览
    print(f"\n{'='*50}")
    print(f"预览前 3 条:")
    for item in all_items[:3]:
        print(f"  [{item.get('offerId')}] {item.get('subject', '')[:40]}")
        print(f"      价格: {item.get('price')} | 30日销量: {item.get('saleQuantity30d')} | 店铺: {item.get('sellerAccount')}")


def list_categories():
    """列出默认的顶级类目（从页面获取）"""
    print("类目列表: 在选品库页面可以看到全部分类\n")


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="店雷达商品数据拉取工具")
    parser.add_argument("keyword", nargs="?", default="女装", help="搜索关键词")
    parser.add_argument("--pages", type=int, default=1, help="拉取页数 (默认1)")
    parser.add_argument("--size", type=int, default=30, help="每页条数 (默认30)")
    parser.add_argument("--sort", default="bookedCount7dGrowthRate",
                        help="排序: bookedCount7dGrowthRate(增长率) | "
                             "bookedCount7d(7日订单) | "
                             "saleCount7d(7日销量) | "
                             "offerRepurchaseRate(复购率) | "
                             "offerCreateTime(上架时间)")

    args = parser.parse_args()
    search_to_file(args.keyword, args.pages, args.size, args.sort)
