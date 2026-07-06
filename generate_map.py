#!/usr/bin/env python3
"""
地图路线规划 - 地址标记生成器
从 CSV 读取地址列表，地理编码后生成 Leaflet 交互式地图 HTML。
支持高德地图 (amap)、天地图 (tianditu)、Nominatim (nominatim) 三种地理编码后端。
"""

import csv
import json
import os
import sys
import time
import hashlib
import argparse
import threading
import concurrent.futures

try:
    import requests
except ImportError:
    sys.exit("缺少依赖: requests。请运行: pip install -r requirements.txt")

# ── 配置加载 ──────────────────────────────────────────────────────────

CONFIG_FILE = "config.json"
OUTPUT_DIR = "output"

with open(CONFIG_FILE, "r", encoding="utf-8") as f:
    config = json.load(f)

AMAP_KEY = config.get("amap_key", "")
TIANDITU_KEY = config.get("tianditu_key", "")
PROXY_CFG = config.get("proxy", {})
GC = config["geocoding"]
MC = config["map"]
DC = config["data"]
MK = config["marker"]

PROVIDER = GC.get("provider", "amap")
RATE_LIMIT = GC["rate_limit"]
GEO_TIMEOUT = GC["timeout"]


# ── 代理配置 ──────────────────────────────────────────────────────────


def build_proxies() -> dict | None:
    """
    构建请求代理字典。
    优先级: config.json > 环境变量 HTTP_PROXY/HTTPS_PROXY > 无代理。
    支持 http://、https://、socks5:// 等协议。
    """
    proxies = {}

    # 从环境变量读取
    for scheme in ["http", "https"]:
        env_val = os.getenv(f"{scheme}_proxy") or os.getenv(f"{scheme.upper()}_proxy")
        if env_val:
            proxies[scheme] = env_val

    # config.json 覆盖环境变量
    cfg_http = PROXY_CFG.get("http", "").strip()
    cfg_https = PROXY_CFG.get("https", "").strip()
    if cfg_http:
        proxies["http"] = cfg_http
    if cfg_https:
        proxies["https"] = cfg_https

    return proxies if proxies else None


PROXIES = build_proxies()
MAX_WORKERS = config.get("max_workers", 1)

# ── 多线程安全 ─────────────────────────────────────────────────────────

_cache_lock = threading.Lock()
_last_req_time = 0.0
_rate_limit_lock = threading.Lock()


def _rate_limit(max_workers: int):
    """跨线程共享速率限制，保证整体 QPS 不超过 1/RATE_LIMIT"""
    global _last_req_time
    if max_workers <= 1:
        time.sleep(RATE_LIMIT)
        return
    with _rate_limit_lock:
        now = time.time()
        elapsed = now - _last_req_time
        if elapsed < RATE_LIMIT:
            time.sleep(RATE_LIMIT - elapsed)
        _last_req_time = time.time()

# ── 产量筛选字段配置 ─────────────────────────────────────────────────

FILTER_NUMERIC_FIELDS = [
    "bookedCount30d", "saleQuantity30d", "salesVolume30d",
    "dayBookedCount", "daySalesVolume", "offerCount", "beFavedCount",
]

FILTER_FIELD_LABELS = {
    "bookedCount30d": "近30日订单数",
    "saleQuantity30d": "近30日销量",
    "salesVolume30d": "近30日销售额(¥)",
    "dayBookedCount": "日订单数",
    "daySalesVolume": "日销售额(¥)",
    "offerCount": "在售商品数",
    "beFavedCount": "收藏数",
}


def parse_float(val) -> float | None:
    """安全解析数值，空值/非数字返回 None"""
    if val is None:
        return None
    try:
        return float(str(val).replace(",", "").strip())
    except (ValueError, TypeError):
        return None


# ── 工具函数 ──────────────────────────────────────────────────────────


def load_cache(cache_path: str) -> dict:
    if os.path.exists(cache_path):
        with open(cache_path, "r", encoding="utf-8") as f:
            return json.load(f)
    return {}


def save_cache(cache: dict, cache_path: str):
    os.makedirs(os.path.dirname(cache_path), exist_ok=True)
    with open(cache_path, "w", encoding="utf-8") as f:
        json.dump(cache, f, ensure_ascii=False, indent=2)
    print(f"  [OK] 缓存已保存 ({len(cache)} 条)")


def cache_key(address: str, province: str, city: str, provider: str = "") -> str:
    raw = f"{provider}|{province}|{city}|{address}".strip()
    return hashlib.md5(raw.encode("utf-8")).hexdigest()


# ── 地理编码后端 ──────────────────────────────────────────────────────


def geocode_amap(address: str, city: str, cache: dict, key: str) -> tuple[float, float] | None:
    """使用高德地图 Geocoding API"""
    url = "https://restapi.amap.com/v3/geocode/geo"
    params = {"key": key, "address": address, "city": city}
    try:
        resp = requests.get(url, params=params, proxies=PROXIES, timeout=GEO_TIMEOUT)
        resp.raise_for_status()
        data = resp.json()
        if data.get("status") == "1" and data.get("geocodes"):
            location = data["geocodes"][0].get("location")
            if location:
                lng, lat = location.split(",")
                return float(lat), float(lng)
        return None
    except Exception as e:
        tag = "[PROXY]" if PROXIES else ""
        print(f"  [ERR] {tag}高德编码失败 [{address}]: {e}")
        return None


def geocode_nominatim(address: str, province: str, city: str, cache: dict) -> tuple[float, float] | None:
    """使用 Nominatim (OSM) Geocoding API"""
    url = "https://nominatim.openstreetmap.org/search"
    query = f"{province} {city} {address}".strip()
    try:
        resp = requests.get(
            url,
            params={"q": query, "format": "json", "limit": 1},
            headers={"User-Agent": "ChangzhouMapGenerator/1.0"},
            proxies=PROXIES,
            timeout=GEO_TIMEOUT,
        )
        resp.raise_for_status()
        data = resp.json()
        if data:
            return float(data[0]["lat"]), float(data[0]["lon"])
        return None
    except Exception as e:
        tag = "[PROXY]" if PROXIES else ""
        print(f"  [ERR] {tag}Nominatim 编码失败 [{query}]: {e}")
        return None


def geocode_tianditu(address: str, cache: dict, key: str) -> tuple[float, float] | None:
    """使用 天地图 Geocoding API"""
    url = "https://api.tianditu.gov.cn/geocoder"
    ds = json.dumps({"keyWord": address}, ensure_ascii=False)
    params = {"ds": ds, "tk": key}
    try:
        resp = requests.get(url, params=params, proxies=PROXIES, timeout=GEO_TIMEOUT)
        resp.raise_for_status()
        data = resp.json()
        if data.get("status") == "0" and data.get("location"):
            loc = data["location"]
            return float(loc["lat"]), float(loc["lon"])
        return None
    except Exception as e:
        tag = "[PROXY]" if PROXIES else ""
        print(f"  [ERR] {tag}天地图编码失败 [{address}]: {e}")
        return None


def geocode_address(
    address: str, province: str, city: str, cache: dict
) -> tuple[float, float] | None:
    """地理编码单个地址（自动选择后端，线程安全）"""
    key = cache_key(address, province, city, PROVIDER)

    with _cache_lock:
        if key in cache:
            cached = cache[key]
            if cached is not None:
                return tuple(cached)
            return None

    _rate_limit(MAX_WORKERS)

    if PROVIDER == "amap":
        coord = geocode_amap(address, city, cache, AMAP_KEY)
    elif PROVIDER == "tianditu":
        full_addr = f"{province}{city}{address}".strip()
        coord = geocode_tianditu(full_addr, cache, TIANDITU_KEY)
    elif PROVIDER == "nominatim":
        coord = geocode_nominatim(address, province, city, cache)
    else:
        print(f"  [ERR] 未知地理编码提供商: {PROVIDER}")
        return None

    if coord:
        with _cache_lock:
            cache[key] = [coord[0], coord[1]]
        return coord
    else:
        with _cache_lock:
            cache[key] = None
        return None


def geocode_all(entries: list[dict], cache: dict, cache_path: str = "", max_workers: int = 1) -> list[dict]:
    """批量地理编码，支持多线程。

    两阶段策略：
      1. 先扫描缓存，缓存命中的立即填入结果（零开销）
      2. 只把未命中的丢进线程池并行请求 API
    """
    total = len(entries)
    print(f"\n{'='*60}")
    print(f"  开始地理编码 (后端: {PROVIDER}) - 共 {total} 个地址")
    if max_workers > 1:
        print(f"  线程数: {max_workers}")
    print(f"{'='*60}\n")

    results: list[dict | None] = [None] * total
    pad = len(str(total))

    # ── 阶段 1：扫描缓存 ──
    uncached_indices: list[int] = []
    for i, entry in enumerate(entries):
        addr = entry.get("address", "").strip()
        province = entry.get("province", "")
        city = entry.get("city", "")
        company = entry.get("company", "") or ""
        key = cache_key(addr, province, city, PROVIDER)

        with _cache_lock:
            if key in cache and cache[key] is not None:
                lat, lon = cache[key]
                results[i] = {**entry, "lat": lat, "lon": lon}
                num = f"[{i+1:>{pad}}/{total}]"
                print(f"  {num} {company[:24]:24s} -> OK (cache)")
                continue

        # 不在缓存中，标记待请求
        if addr:
            uncached_indices.append(i)

    if not uncached_indices:
        print(f"\n  全部命中缓存！成功编码 {total}/{total} 个地址\n")
        return [r for r in results if r is not None]

    print(f"\n  -> 缓存命中 {total - len(uncached_indices)}/{total}，需请求 API: {len(uncached_indices)} 条\n")

    # ── 阶段 2：多线程请求 API ──
    def fetch_one(idx: int) -> tuple[int, dict | None, str]:
        entry = entries[idx]
        addr = entry.get("address", "").strip()
        province = entry.get("province", "")
        city = entry.get("city", "")
        company = entry.get("company", "") or ""

        coord = geocode_address(addr, province, city, cache)
        if coord:
            result = {**entry, "lat": coord[0], "lon": coord[1]}
            with _cache_lock:
                key = cache_key(addr, province, city, PROVIDER)
                cache[key] = [coord[0], coord[1]]
                if cache_path:
                    save_cache(cache, cache_path)
            return idx, result, "OK"
        else:
            return idx, None, "跳过: 地址解析失败"

    if max_workers <= 1:
        for idx in uncached_indices:
            _idx, result, status = fetch_one(idx)
            company = entries[idx].get("company", "") or ""
            num = f"[{idx+1:>{pad}}/{total}]"
            print(f"  {num} {company[:24]:24s} -> {status}")
            results[idx] = result
    else:
        with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers) as executor:
            fut_map = {executor.submit(fetch_one, idx): idx for idx in uncached_indices}
            for future in concurrent.futures.as_completed(fut_map):
                idx, result, status = future.result()
                company = entries[idx].get("company", "") or ""
                num = f"[{idx+1:>{pad}}/{total}]"
                print(f"  {num} {company[:24]:24s} -> {status}")
                results[idx] = result

    ordered = [r for r in results if r is not None]
    print(f"\n  完成！成功编码 {len(ordered)}/{total} 个地址\n")
    return ordered


# ── 地图 HTML 生成 ────────────────────────────────────────────────────


def build_map_html(entries: list[dict], tianditu_key: str = "", tile_style: str = "clean") -> str:
    """生成 Leaflet 交互式地图 HTML"""
    center_lat, center_lon = MC["center"]
    zoom = MC["zoom"]
    cluster_radius = MC["max_cluster_radius"]
    tile_style = MC.get("tile_style", "clean")

    features = []
    factory_count = 0
    non_factory_count = 0

    for e in entries:
        is_factory = str(e.get("isFactory", "")).strip() == "True"
        color = MK["factory_color"] if is_factory else MK["non_factory_color"]
        marker_size = MK["size"]
        opacity = MK["opacity"]

        if is_factory:
            factory_count += 1
        else:
            non_factory_count += 1

        feature = {
            "lat": e["lat"],
            "lon": e["lon"],
            "name": e.get("company", ""),
            "address": e.get("address", ""),
            "isFactory": is_factory,
            "color": color,
            "size": marker_size,
            "opacity": opacity,
        }
        # 附带产量筛选字段
        for field in FILTER_NUMERIC_FIELDS:
            feature[field] = parse_float(e.get(field, ""))
        features.append(feature)

    features_json = json.dumps(features, ensure_ascii=False)

    # 字段配置，传给 JS 动态构建筛选 UI
    field_cfg = [
        {"key": k, "label": FILTER_FIELD_LABELS.get(k, k),
         "unit": "(¥)" if k in ("salesVolume30d", "daySalesVolume") else "(单)" if "Count" in k else ""}
        for k in FILTER_NUMERIC_FIELDS
    ]
    field_cfg_json = json.dumps(field_cfg, ensure_ascii=False)
    field_labels_json = json.dumps(FILTER_FIELD_LABELS, ensure_ascii=False)

    html = f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>常州商家分布地图</title>
<link rel="stylesheet" href="https://cdn.jsdelivr.net/npm/leaflet@1.9.4/dist/leaflet.css" />
<link rel="stylesheet" href="https://cdn.jsdelivr.net/npm/leaflet.markercluster@1.5.3/dist/MarkerCluster.css" />
<link rel="stylesheet" href="https://cdn.jsdelivr.net/npm/leaflet.markercluster@1.5.3/dist/MarkerCluster.Default.css" />
<style>
  * {{ margin: 0; padding: 0; box-sizing: border-box; }}
  html, body {{ height: 100%; font-family: -apple-system, 'Helvetica Neue', 'PingFang SC', 'Microsoft YaHei', sans-serif; }}
  #map {{ height: 100%; width: 100%; }}

  .custom-marker {{
    display: flex; align-items: center; justify-content: center;
    border-radius: 50%;
    border: 3px solid #fff;
    box-shadow: 0 2px 8px rgba(0,0,0,0.35), 0 0 12px var(--glow-color, rgba(0,0,0,0.3));
    font-weight: bold;
    color: #fff;
    font-size: 13px;
    cursor: pointer;
    transition: transform 0.2s ease, box-shadow 0.2s ease;
  }}
  .custom-marker:hover {{
    transform: scale(1.3);
    box-shadow: 0 4px 20px rgba(0,0,0,0.5), 0 0 25px var(--glow-color, rgba(0,0,0,0.5));
    z-index: 1000 !important;
  }}

  @keyframes marker-pulse {{
    0%   {{ box-shadow: 0 0 0 0 var(--pulse-color, rgba(231,76,60,0.5)); }}
    70%  {{ box-shadow: 0 0 0 14px transparent; }}
    100% {{ box-shadow: 0 0 0 0 transparent; }}
  }}
  .marker-pulse {{
    animation: marker-pulse 2.5s ease-out infinite;
  }}

  .popup-content {{
    min-width: 180px;
    padding: 4px 0;
  }}
  .popup-content h3 {{
    font-size: 15px;
    font-weight: 600;
    margin-bottom: 6px;
    color: #2c3e50;
  }}
  .popup-content .popup-address {{
    font-size: 12px;
    color: #7f8c8d;
    margin-bottom: 4px;
  }}
  .popup-content .popup-tag {{
    display: inline-block;
    font-size: 11px;
    padding: 2px 8px;
    border-radius: 10px;
    color: #fff;
    font-weight: 500;
  }}
  .popup-content .popup-tag.factory {{ background: {MK['factory_color']}; }}
  .popup-content .popup-tag.shop   {{ background: {MK['non_factory_color']}; }}

  .legend {{
    position: absolute;
    bottom: 30px;
    right: 20px;
    z-index: 1000;
    background: rgba(255,255,255,0.95);
    padding: 14px 18px;
    border-radius: 10px;
    box-shadow: 0 2px 12px rgba(0,0,0,0.15);
    font-size: 13px;
    line-height: 1.8;
    min-width: 130px;
    backdrop-filter: blur(4px);
  }}
  .legend-title {{
    font-weight: 600;
    font-size: 13px;
    color: #2c3e50;
    margin-bottom: 6px;
    border-bottom: 1px solid #eee;
    padding-bottom: 4px;
  }}
  .legend-item {{
    display: flex;
    align-items: center;
    gap: 8px;
    margin: 3px 0;
  }}
  .legend-dot {{
    width: 16px; height: 16px; border-radius: 50%;
    border: 2px solid #fff;
    box-shadow: 0 1px 3px rgba(0,0,0,0.2);
    flex-shrink: 0;
  }}
  .legend-count {{
    color: #95a5a6;
    font-size: 12px;
    margin-left: auto;
  }}

  .stats-bar {{
    position: absolute;
    top: 16px;
    left: 50%;
    transform: translateX(-50%);
    z-index: 1000;
    background: rgba(255,255,255,0.92);
    padding: 8px 20px;
    border-radius: 20px;
    box-shadow: 0 2px 10px rgba(0,0,0,0.12);
    font-size: 13px;
    color: #555;
    backdrop-filter: blur(4px);
    white-space: nowrap;
    pointer-events: none;
  }}
  .stats-bar strong {{ color: #2c3e50; }}

  /* ── 筛选面板 ────────────────────────────────────────────── */
  #filterToggle {{
    position: absolute; top: 70px; right: 0; z-index: 1000;
    width: 36px; height: 36px; border: none; border-radius: 0 6px 6px 0;
    background: rgba(255,255,255,0.95); color: #555;
    font-size: 18px; cursor: pointer;
    box-shadow: 2px 2px 8px rgba(0,0,0,0.12);
    transition: right 0.3s ease;
    display: flex; align-items: center; justify-content: center;
  }}
  #filterToggle:hover {{ background: #f0f0f0; }}
  #filterToggle.open {{ right: 310px; }}

  #filterPanel {{
    position: absolute; top: 0; right: -310px; z-index: 1001;
    width: 300px; height: 100%;
    background: rgba(255,255,255,0.97);
    box-shadow: -2px 0 16px rgba(0,0,0,0.12);
    transition: right 0.3s ease;
    display: flex; flex-direction: column;
    font-size: 13px; color: #333;
    backdrop-filter: blur(6px);
  }}
  #filterPanel.open {{ right: 0; }}

  .filter-header {{
    padding: 14px 16px 10px;
    border-bottom: 1px solid #eee;
    display: flex; justify-content: space-between; align-items: center;
    flex-shrink: 0;
  }}
  .filter-header h3 {{
    margin: 0; font-size: 15px; font-weight: 600; color: #2c3e50;
  }}
  .filter-header button {{
    border: none; background: none; font-size: 18px; cursor: pointer;
    color: #999; padding: 0 4px;
  }}
  .filter-header button:hover {{ color: #333; }}

  .filter-body {{
    flex: 1; overflow-y: auto; padding: 10px 0;
  }}

  .filter-section {{
    padding: 0 16px 10px; margin-bottom: 6px;
  }}
  .filter-section-title {{
    font-size: 12px; font-weight: 600; color: #888;
    text-transform: uppercase; letter-spacing: 0.5px;
    margin-bottom: 8px; padding-bottom: 4px;
    border-bottom: 1px solid #eee;
  }}

  /* 工厂复选框行 */
  .factory-check-row {{
    display: flex; gap: 16px; margin: 4px 0;
  }}
  .factory-check-row label {{
    display: flex; align-items: center; gap: 5px;
    cursor: pointer; font-size: 13px;
    padding: 3px 0;
  }}
  .factory-check-row input[type="checkbox"] {{
    accent-color: #3498db; width: 15px; height: 15px; cursor: pointer;
  }}

  /* 产量字段行 */
  .filter-field {{
    margin: 3px 0; padding: 6px 8px; border-radius: 6px;
    transition: background 0.15s;
  }}
  .filter-field:hover {{ background: #f5f6fa; }}
  .filter-field-header {{
    display: flex; align-items: center; gap: 6px;
  }}
  .filter-field-header input[type="checkbox"] {{
    accent-color: #3498db; width: 14px; height: 14px; cursor: pointer; flex-shrink: 0;
  }}
  .filter-field-header .field-label {{
    font-size: 12px; color: #555; cursor: pointer; flex: 1;
  }}
  .filter-field-header .field-unit {{
    font-size: 11px; color: #aaa;
  }}

  .filter-range {{
    display: flex; align-items: center; gap: 6px;
    margin-top: 5px; margin-left: 20px;
  }}
  .filter-range input[type="number"] {{
    width: 70px; padding: 3px 6px; border: 1px solid #ddd;
    border-radius: 4px; font-size: 12px; text-align: center;
    outline: none; transition: border-color 0.15s;
  }}
  .filter-range input[type="number"]:focus {{
    border-color: #3498db; box-shadow: 0 0 0 2px rgba(52,152,219,0.12);
  }}
  .filter-range input[type="number"]:disabled {{
    background: #f5f5f5; color: #ccc;
  }}
  .filter-range .range-sep {{
    color: #bbb; font-size: 12px;
  }}

  /* 快捷按钮 */
  .filter-actions {{
    padding: 10px 16px 14px; border-top: 1px solid #eee;
    display: flex; gap: 8px; flex-shrink: 0;
  }}
  .filter-actions button {{
    flex: 1; padding: 6px 0; border: 1px solid #ddd; border-radius: 6px;
    background: #fff; font-size: 12px; cursor: pointer; color: #555;
    transition: all 0.15s;
  }}
  .filter-actions button:hover {{
    background: #f0f0f0; border-color: #bbb;
  }}
  .filter-actions button.primary {{
    background: #3498db; color: #fff; border-color: #3498db;
  }}
  .filter-actions button.primary:hover {{
    background: #2980b9;
  }}
  .filter-actions button.success {{
    background: #27ae60; color: #fff; border-color: #27ae60;
  }}
  .filter-actions button.success:hover {{
    background: #219a52;
  }}
  .filter-actions button.warning {{
    background: #e67e22; color: #fff; border-color: #e67e22;
  }}
  .filter-actions button.warning:hover {{
    background: #d35400;
  }}

  /* 定位按钮进度状态 */
  .filter-actions button.locating {{
    background: #f39c12; color: #fff; border-color: #f39c12;
    animation: locate-pulse 1.5s ease-in-out infinite;
    pointer-events: none;
  }}
  @keyframes locate-pulse {{
    0%, 100% {{ opacity: 1; }}
    50% {{ opacity: 0.6; }}
  }}

  /* 最近商家结果横幅 */
  #locateResult {{
    position: absolute; top: 60px; left: 50%; transform: translateX(-50%);
    z-index: 999; display: none;
    background: rgba(255,255,255,0.95);
    padding: 10px 20px; border-radius: 12px;
    box-shadow: 0 4px 20px rgba(0,0,0,0.18);
    font-size: 13px; color: #333;
    backdrop-filter: blur(6px);
    max-width: 80%;
    text-align: center;
    border: 1px solid rgba(39,174,96,0.25);
    pointer-events: none;
    white-space: nowrap;
  }}
  #locateResult .dist {{
    font-weight: 700; color: #27ae60; font-size: 15px;
  }}
  #locateResult .shop-name {{
    font-weight: 600; color: #2c3e50;
  }}
  #locateResult .locate-close {{
    margin-left: 12px; cursor: pointer; color: #bbb; font-size: 16px;
    pointer-events: auto;
  }}
  #locateResult .locate-close:hover {{ color: #555; }}

  #locateResult.show {{ display: inline-block; }}

  /* 定位失败提示 */
  #locateError {{
    position: absolute; top: 60px; left: 50%; transform: translateX(-50%);
    z-index: 999; display: none;
    background: rgba(255,255,255,0.95);
    padding: 8px 18px; border-radius: 10px;
    box-shadow: 0 2px 12px rgba(0,0,0,0.12);
    font-size: 12px; color: #e74c3c;
    backdrop-filter: blur(4px);
    white-space: nowrap;
    border: 1px solid rgba(231,76,60,0.2);
  }}
  #locateError.show {{ display: block; }}

  .filter-count {{
    padding: 0 16px 8px; font-size: 12px; color: #999;
    flex-shrink: 0;
  }}

  /* 空状态提示 */
  .filter-empty {{
    position: absolute; top: 50%; left: 50%; transform: translate(-50%, -50%);
    text-align: center; color: #ccc; font-size: 14px;
    pointer-events: none; display: none;
  }}
</style>
</head>
<body>

<div id="map"></div>

<div class="stats-bar">
  &#128205; 共标记 <strong>{len(entries)}</strong> 家店铺 &#183;
  工厂 <strong style="color:{MK['factory_color']}">{factory_count}</strong> 家 &#183;
  非工厂 <strong style="color:{MK['non_factory_color']}">{non_factory_count}</strong> 家
</div>

<div class="legend">
  <div class="legend-title">图例</div>
  <div class="legend-item">
    <div class="legend-dot" style="background:{MK['factory_color']};"></div>
    <span>工厂</span>
    <span class="legend-count">{factory_count}</span>
  </div>
  <div class="legend-item">
    <div class="legend-dot" style="background:{MK['non_factory_color']};"></div>
    <span>非工厂</span>
    <span class="legend-count">{non_factory_count}</span>
  </div>
</div>

<!-- ── 筛选面板 ──────────────────────────────────────────── -->
<button id="filterToggle" title="筛选">&#9776;</button>

<div id="filterPanel">
  <div class="filter-header">
    <h3>筛选条件</h3>
    <button id="filterClose">&times;</button>
  </div>

  <div class="filter-body">
    <div class="filter-section">
      <div class="filter-section-title">商家类型</div>
      <div class="factory-check-row">
        <label><input type="checkbox" id="ff-factory" checked>
          <span style="display:inline-block;width:10px;height:10px;border-radius:50%;background:{MK['factory_color']};margin-right:2px;"></span> 工厂</label>
        <label><input type="checkbox" id="ff-nonfactory" checked>
          <span style="display:inline-block;width:10px;height:10px;border-radius:50%;background:{MK['non_factory_color']};margin-right:2px;"></span> 非工厂</label>
      </div>
    </div>

    <div class="filter-section">
      <div class="filter-section-title">产量筛选 <span style="font-weight:400;color:#bbb;font-size:11px;">&#183; 勾选启用</span></div>
      <div id="numericFilters"></div>
    </div>
  </div>

  <div class="filter-count" id="filterCount"></div>
  <div class="filter-actions">
    <button id="filterReset">重置</button>
    <button id="filterClearAll" class="primary">清空全部筛选</button>
    <button id="locateBtn" class="success" title="使用浏览器定位，找到离你最近的商家">&#128205; 最近商家</button>
  </div>
</div>

<div id="locateResult"><span class="shop-name"></span> &middot; 距离 <span class="dist"></span> <span class="locate-close" id="locateResultClose">&times;</span></div>
<div id="locateError"></div>

<div class="filter-empty" id="filterEmpty">&#128200; 没有符合条件的结果<br><span style="font-size:12px;">请调整筛选条件</span></div>

<script src="https://cdn.jsdelivr.net/npm/leaflet@1.9.4/dist/leaflet.js"></script>
<script src="https://cdn.jsdelivr.net/npm/leaflet.markercluster@1.5.3/dist/leaflet.markercluster.js"></script>
<script>
(function() {{
  'use strict';

  var map = L.map('map', {{
    center: [{center_lat}, {center_lon}],
    zoom: {zoom},
    zoomControl: true,
  }});

  // ── 地图底图 ──────────────────────────────────────────────────
  // style: clean（高德路网，极简+中文）/ gray（CartoDB 浅灰）/ tianditu（天地图）/ osm（OpenStreetMap）
  var style = "{tile_style}";
  var tdtKey = "{tianditu_key}";

  if (style === 'tianditu' && tdtKey) {{
    L.tileLayer('https://t0.tianditu.gov.cn/DataServer?T=vec_w&X={{x}}&Y={{y}}&L={{z}}&tk=' + tdtKey, {{
      attribution: '&copy; 天地图',
      maxZoom: 18,
    }}).addTo(map);
    L.tileLayer('https://t0.tianditu.gov.cn/DataServer?T=cva_w&X={{x}}&Y={{y}}&L={{z}}&tk=' + tdtKey, {{
      attribution: '&copy; 天地图',
      maxZoom: 18,
    }}).addTo(map);
  }} else if (style === 'clean') {{
    L.tileLayer('https://webrd01.is.autonavi.com/appmaptile?lang=zh_cn&size=1&scale=1&style=8&x={{x}}&y={{y}}&z={{z}}', {{
      attribution: '&copy; 高德地图',
      maxZoom: 18,
    }}).addTo(map);
  }} else if (style === 'gray') {{
    L.tileLayer('https://{{s}}.basemaps.cartocdn.com/light_all/{{z}}/{{x}}/{{y}}{{r}}.png', {{
      attribution: '&copy; <a href="https://www.openstreetmap.org/copyright">OSM</a>, &copy; <a href="https://carto.com">CARTO</a>',
      maxZoom: 19,
    }}).addTo(map);
  }} else {{
    L.tileLayer('https://{{s}}.tile.openstreetmap.org/{{z}}/{{x}}/{{y}}.png', {{
      attribution: '&copy; <a href="https://openstreetmap.org/copyright">OpenStreetMap</a>',
      maxZoom: 19,
    }}).addTo(map);
  }}

  var markers = L.markerClusterGroup({{
    maxClusterRadius: {cluster_radius},
    spiderfyOnMaxZoom: true,
    showCoverageOnHover: false,
    disableClusteringAtZoom: 15,
    iconCreateFunction: function (cluster) {{
      var count = cluster.getChildCount();
      var size = 40;
      if (count >= 20) size = 54;
      else if (count >= 10) size = 48;
      return L.divIcon({{
        html: '<div style="'
          + 'width:' + size + 'px;height:' + size + 'px;'
          + 'background:rgba(52,152,219,0.85);'
          + 'border:3px solid #fff;border-radius:50%;'
          + 'display:flex;align-items:center;justify-content:center;'
          + 'font-weight:700;font-size:13px;color:#fff;'
          + 'box-shadow:0 2px 10px rgba(0,0,0,0.3);'
          + '">' + count + '</div>',
        className: '',
        iconSize: [size, size],
        iconAnchor: [size/2, size/2],
      }});
    }},
  }});

  var features = {features_json};
  var FIELD_CFG = {field_cfg_json};
  var FIELD_LABELS = {field_labels_json};

  // ── 构建筛选面板的产量字段 UI ──────────────────────────────────────
  var numericContainer = document.getElementById('numericFilters');
  FIELD_CFG.forEach(function(f) {{
    var div = document.createElement('div');
    div.className = 'filter-field';

    var enabled = true; // default enabled

    div.innerHTML =
      '<div class="filter-field-header">'
        + '<input type="checkbox" class="ff-toggle" id="ff-' + f.key + '" checked>'
        + '<span class="field-label">' + f.label + '</span>'
        + '<span class="field-unit">' + (f.unit || '') + '</span>'
      + '</div>'
      + '<div class="filter-range">'
        + '<input type="number" class="ff-min" id="ff-min-' + f.key + '" placeholder="最小值" step="any">'
        + '<span class="range-sep">—</span>'
        + '<input type="number" class="ff-max" id="ff-max-' + f.key + '" placeholder="最大值" step="any">'
      + '</div>';
    numericContainer.appendChild(div);
  }});

  // ── 构建标记 ───────────────────────────────────────────────────────
  var markerDataList = []; // {{marker, data}}

  features.forEach(function(f) {{
    var pulse = f.isFactory ? ' marker-pulse' : '';
    var glowColor = f.color;

    var icon = L.divIcon({{
      html: '<div class="custom-marker' + pulse + '" style="'
        + 'width:' + f.size + 'px;height:' + f.size + 'px;'
        + 'background:' + f.color + ';'
        + '--glow-color:' + glowColor + '80;'
        + '--pulse-color:' + glowColor + '60;'
        + 'opacity:' + f.opacity + ';'
        + 'font-size:' + Math.max(10, f.size - 6) + 'px;'
        + '">' + (f.isFactory ? '&#9733;' : '&#9679;') + '</div>',
      className: '',
      iconSize: [f.size, f.size],
      iconAnchor: [f.size/2, f.size/2],
    }});

    var marker = L.marker([f.lat, f.lon], {{ icon: icon }});

    var tagClass = f.isFactory ? 'factory' : 'shop';
    var tagLabel = f.isFactory ? '工厂' : '非工厂';
    var popupLines = '<div class="popup-content">'
      + '<h3>' + f.name + '</h3>'
      + '<div class="popup-address">' + f.address + '</div>'
      + '<span class="popup-tag ' + tagClass + '">' + tagLabel + '</span>';
    // 在弹窗中显示产量数据
    FIELD_CFG.forEach(function(cfg) {{
      var v = f[cfg.key];
      if (v !== null && v !== undefined) {{
        var formatted = cfg.key === 'salesVolume30d' || cfg.key === 'daySalesVolume'
          ? '¥' + Number(v).toLocaleString('zh-CN', {{maximumFractionDigits:2}})
          : Number(v).toLocaleString('zh-CN');
        popupLines += '<div style="font-size:11px;color:#888;margin-top:3px;">'
          + cfg.label + ': <strong>' + formatted + '</strong></div>';
      }}
    }});
    popupLines += '</div>';

    marker.bindPopup(popupLines, {{
      closeButton: true,
      maxWidth: 300,
    }});

    markerDataList.push({{marker: marker, data: f}});
  }});

  // ── 筛选函数 ───────────────────────────────────────────────────────
  function applyFilters() {{
    var showFactory = document.getElementById('ff-factory').checked;
    var showNonFactory = document.getElementById('ff-nonfactory').checked;

    // 读取数值筛选条件
    var fieldFilters = [];
    FIELD_CFG.forEach(function(f) {{
      var enabled = document.getElementById('ff-' + f.key).checked;
      var minVal = parseFloat(document.getElementById('ff-min-' + f.key).value);
      var maxVal = parseFloat(document.getElementById('ff-max-' + f.key).value);
      fieldFilters.push({{
        key: f.key,
        enabled: enabled,
        min: isNaN(minVal) ? null : minVal,
        max: isNaN(maxVal) ? null : maxVal,
      }});
    }});

    markers.clearLayers();
    var visibleCount = 0;

    markerDataList.forEach(function(md) {{
      var d = md.data;

      // 1. 商家类型筛选
      if (d.isFactory && !showFactory) return;
      if (!d.isFactory && !showNonFactory) return;

      // 2. 数值字段筛选
      var pass = true;
      for (var i = 0; i < fieldFilters.length; i++) {{
        var ff = fieldFilters[i];
        if (!ff.enabled) continue;

        var val = d[ff.key];
        if (val === null || val === undefined) {{ pass = false; break; }}
        if (ff.min !== null && val < ff.min) {{ pass = false; break; }}
        if (ff.max !== null && val > ff.max) {{ pass = false; break; }}
      }}
      if (!pass) return;

      markers.addLayer(md.marker);
      visibleCount++;
    }});

    // 更新计数
    document.getElementById('filterCount').textContent =
      '显示 ' + visibleCount + ' / ' + markerDataList.length + ' 家';

    // 空状态提示
    var emptyEl = document.getElementById('filterEmpty');
    emptyEl.style.display = visibleCount === 0 ? 'block' : 'none';
  }}

  // ── 绑定事件 ───────────────────────────────────────────────────────
  // 工厂/非工厂
  document.getElementById('ff-factory').addEventListener('change', applyFilters);
  document.getElementById('ff-nonfactory').addEventListener('change', applyFilters);

  // 数值字段
  FIELD_CFG.forEach(function(f) {{
    document.getElementById('ff-' + f.key).addEventListener('change', applyFilters);
    document.getElementById('ff-min-' + f.key).addEventListener('input', applyFilters);
    document.getElementById('ff-max-' + f.key).addEventListener('input', applyFilters);
  }});

  // 面板开合
  var panel = document.getElementById('filterPanel');
  var toggleBtn = document.getElementById('filterToggle');
  var closeBtn = document.getElementById('filterClose');

  toggleBtn.addEventListener('click', function() {{
    var open = panel.classList.toggle('open');
    toggleBtn.classList.toggle('open');
    toggleBtn.innerHTML = open ? '&#10005;' : '&#9776;';
  }});
  closeBtn.addEventListener('click', function() {{
    panel.classList.remove('open');
    toggleBtn.classList.remove('open');
    toggleBtn.innerHTML = '&#9776;';
  }});

  // 重置
  document.getElementById('filterReset').addEventListener('click', function() {{
    document.getElementById('ff-factory').checked = true;
    document.getElementById('ff-nonfactory').checked = true;
    FIELD_CFG.forEach(function(f) {{
      document.getElementById('ff-' + f.key).checked = true;
      document.getElementById('ff-min-' + f.key).value = '';
      document.getElementById('ff-max-' + f.key).value = '';
    }});
    applyFilters();
  }});

  // 清空全部
  document.getElementById('filterClearAll').addEventListener('click', function() {{
    document.getElementById('ff-factory').checked = false;
    document.getElementById('ff-nonfactory').checked = false;
    FIELD_CFG.forEach(function(f) {{
      document.getElementById('ff-' + f.key).checked = false;
    }});
    applyFilters();
  }});

  // ── 定位最近商家 ───────────────────────────────────────────────────
  var locateBtn = document.getElementById('locateBtn');
  var locateResult = document.getElementById('locateResult');
  var locateError = document.getElementById('locateError');
  var locateCircle = null;
  var locateMarker = null;

  // 筛选变化时隐藏定位结果
  var origApply = applyFilters;
  applyFilters = function() {{
    origApply();
    hideLocateResult();
  }};

  function hideLocateResult() {{
    locateResult.classList.remove('show');
    locateError.classList.remove('show');
    locateBtn.className = 'success';
    locateBtn.textContent = '\\u{{1F4CD}} \u6700\u8FD1\u5546\u5BB6';
    if (locateCircle) {{ map.removeLayer(locateCircle); locateCircle = null; }}
    if (locateMarker) {{ map.removeLayer(locateMarker); locateMarker = null; }}
  }}

  function formatDistance(meters) {{
    if (meters < 1000) return Math.round(meters) + ' m';
    return (meters / 1000).toFixed(1) + ' km';
  }}

  document.getElementById('locateResultClose').addEventListener('click', hideLocateResult);

  locateBtn.addEventListener('click', function() {{
    // 先检查是否有可见标记
    var visibleBounds = markers.getLayers().length;
    if (visibleBounds === 0) {{
      locateError.textContent = '当前没有可见的商家，请调整筛选条件后重试';
      locateError.classList.add('show');
      return;
    }}

    // 隐藏上次结果
    hideLocateResult();

    locateBtn.className = 'locating';
    locateBtn.textContent = '\\u{{1F550}} \u5B9A\u4F4D\u4E2D...';

    map.locate({{
      setView: false,
      enableHighAccuracy: true,
      timeout: 15000,
      maximumAge: 30000,
    }});
  }});

  map.on('locationfound', function(e) {{
    var userLatLng = e.latlng;
    var nearest = null;
    var nearestDist = Infinity;

    // 只在可见标记中寻找
    markers.eachLayer(function(marker) {{
      var d = userLatLng.distanceTo(marker.getLatLng());
      if (d < nearestDist) {{
        nearestDist = d;
        nearest = marker;
      }}
    }});

    if (!nearest) {{
      locateError.textContent = '未找到可见商家，请调整筛选条件';
      locateError.classList.add('show');
      locateBtn.className = 'success';
      locateBtn.textContent = '\\u{{1F4CD}} \u6700\u8FD1\u5546\u5BB6';
      return;
    }}

    // 在地图缩放不稳定时调整视野
    var bounds = markers.getBounds();
    if (bounds) {{
      // 如果用户位置不在当前视野内，或者距离很远，移动视野
      if (!bounds.contains(userLatLng) || nearestDist > 5000) {{
        // 同时显示用户位置和最近商家
        var group = L.featureGroup([nearest, L.marker(userLatLng)]);
        map.fitBounds(group.getBounds().pad(0.3));
      }} else {{
        map.setView(nearest.getLatLng(), Math.max(map.getZoom(), 14));
      }}
    }}

    // 打开最近商家的弹窗
    nearest.openPopup();

    // 显示用户位置圆圈
    locateCircle = L.circle(userLatLng, {{
      radius: nearestDist,
      color: '#27ae60',
      fillColor: '#27ae60',
      fillOpacity: 0.08,
      weight: 2,
      opacity: 0.3,
      dashArray: '6, 6',
    }}).addTo(map);

    // 用户位置标记
    locateMarker = L.marker(userLatLng, {{
      icon: L.divIcon({{
        html: '<div style="width:18px;height:18px;background:#27ae60;border:3px solid #fff;border-radius:50%;box-shadow:0 0 0 4px rgba(39,174,96,0.3);"></div>',
        className: '',
        iconSize: [18, 18],
        iconAnchor: [9, 9],
      }}),
      zIndexOffset: 10000,
    }}).addTo(map);

    // 显示结果横幅
    var nearestData = null;
    for (var i = 0; i < markerDataList.length; i++) {{
      if (markerDataList[i].marker === nearest) {{
        nearestData = markerDataList[i].data;
        break;
      }}
    }}
    var nameText = nearestData ? nearestData.name : '未知商家';
    locateResult.querySelector('.shop-name').textContent = nameText;
    locateResult.querySelector('.dist').textContent = formatDistance(nearestDist);
    locateResult.classList.add('show');

    locateBtn.className = 'success';
      locateBtn.textContent = '\\u{{1F4CD}} \u6700\u8FD1\u5546\u5BB6';
  }});

  map.on('locationerror', function(e) {{
    var msg = '';
    if (e.code === 1) msg = '\u5B9A\u4F4D\u88AB\u62D2\u7EDD\uFF0C\u8BF7\u5728\u6D4F\u89C8\u5668\u8BBE\u7F6E\u4E2D\u5141\u8BB8\u4F4D\u7F6E\u8BBF\u95EE';
    else if (e.code === 2) msg = '\u5B9A\u4F4D\u5931\u8D25\uFF0C\u65E0\u6CD5\u83B7\u53D6\u4F4D\u7F6E\u4FE1\u606F';
    else if (e.code === 3) msg = '\u5B9A\u4F4D\u8D85\u65F6\uFF0C\u8BF7\u68C0\u67E5\u7F51\u7EDC\u6216GPS';
    else msg = '\u5B9A\u4F4D\u5931\u8D25: ' + (e.message || '\u672A\u77E5\u9519\u8BEF');

    locateError.textContent = msg;
    locateError.classList.add('show');
    locateBtn.className = 'success';
      locateBtn.textContent = '\\u{{1F4CD}} \u6700\u8FD1\u5546\u5BB6';
  }});
  if (markerDataList.length > 0) {{
    markers.addLayer(markerDataList[0].marker); // 临时加一个避免空group报错
  }}
  map.addLayer(markers);
  applyFilters();

  // 调整视野
  if (features.length > 0) {{
    var group = L.featureGroup(
      features.map(function(f) {{
        return L.marker([f.lat, f.lon]);
      }})
    );
    map.fitBounds(group.getBounds().pad(0.08));
  }}
}})();
</script>
</body>
</html>"""

    return html


# ── 主流程 ────────────────────────────────────────────────────────────


def main():
    parser = argparse.ArgumentParser(description="地址标记地图生成器")
    parser.add_argument("--csv", help="CSV 文件路径（覆盖 config.json）")
    parser.add_argument("--output-dir", default=OUTPUT_DIR, help="输出目录（默认: output）")
    parser.add_argument("--provider", help="地理编码后端: amap / tianditu / nominatim")
    parser.add_argument("--tile-style", help="地图底图风格: clean(高德路网-极简+中文) / gray(CartoDB浅灰) / tianditu(天地图) / osm(OpenStreetMap)")
    parser.add_argument("--workers", type=int, default=MAX_WORKERS, help="地理编码线程数（默认: 1，多线程可显著提速）")
    args = parser.parse_args()

    output_dir = args.output_dir
    cache_path = os.path.join(output_dir, "geocode_cache.json")
    map_path = os.path.join(output_dir, "changzhou_shops_map.html")

    # CLI 参数覆盖 config
    if args.csv:
        DC["csv_file"] = args.csv
    if args.provider:
        global PROVIDER
        PROVIDER = args.provider
    if args.tile_style:
        MC["tile_style"] = args.tile_style

    print("=" * 60)
    print("  常州商家地址 - 地图标记生成器")
    print("=" * 60)

    # 检查 API Key
    if PROVIDER == "amap" and not AMAP_KEY:
        print()
        print("  [ERR] 使用高德地图编码需要 API Key。")
        print()
        print("  请前往 https://lbs.amap.com/ 免费注册并创建应用")
        print("  获取 Key 后填入 config.json 的 amap_key 字段。")
        print()
        sys.exit(1)

    if PROVIDER == "tianditu" and not TIANDITU_KEY:
        print()
        print("  [ERR] 使用天地图编码需要 API Key。")
        print()
        print("  请前往 https://console.tianditu.gov.cn/ 注册并创建应用")
        print("  获取 Key 后填入 config.json 的 tianditu_key 字段。")
        print()
        sys.exit(1)

    # 1. 读 CSV
    csv_path = DC["csv_file"]
    if not os.path.exists(csv_path):
        sys.exit(f"[ERR] CSV 文件不存在: {csv_path}")

    print(f"\n-> 读取 CSV: {csv_path}")
    entries = []
    with open(csv_path, "r", encoding=DC["encoding"]) as f:
        reader = csv.DictReader(f)
        for row in reader:
            entries.append(row)

    print(f"   共 {len(entries)} 条记录")

    # 2. 过滤空地址
    if DC["filter_empty_address"]:
        before = len(entries)
        entries = [e for e in entries if e.get("address", "").strip()]
        print(f"\n-> 过滤空地址: {before} -> {len(entries)} 条")

    # 3. 地理编码（每条结果即时存缓存，崩了不丢进度）
    cache = load_cache(cache_path)
    cached_count = sum(1 for v in cache.values() if v is not None)
    print(f"   缓存命中: {cached_count} 条")
    geocoded = geocode_all(entries, cache, cache_path=cache_path, max_workers=args.workers)

    if not geocoded:
        print("[ERR] 没有成功编码的地址，无法生成地图")
        sys.exit(1)

    # 4. 生成地图 HTML
    print(f"\n{'='*60}")
    print(f"  -> 生成地图 HTML")
    print(f"{'='*60}\n")

    ts = MC.get("tile_style", "clean")
    html = build_map_html(geocoded, tianditu_key=TIANDITU_KEY, tile_style=ts)
    os.makedirs(output_dir, exist_ok=True)
    with open(map_path, "w", encoding="utf-8") as f:
        f.write(html)

    abs_path = os.path.abspath(map_path)
    print(f"  [OK] 地图已生成: {abs_path}")
    print(f"  [OK] 缓存已保存: {os.path.abspath(cache_path)}")
    print(f"  [OK] 共标记 {len(geocoded)} 个地址")
    print(f"\n  -> 用浏览器直接打开 {map_path} 即可查看地图\n")


if __name__ == "__main__":
    main()
