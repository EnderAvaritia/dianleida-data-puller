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
    """地理编码单个地址（自动选择后端）"""
    key = cache_key(address, province, city, PROVIDER)

    if key in cache:
        cached = cache[key]
        if cached is not None:
            return tuple(cached)
        return None

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
        cache[key] = [coord[0], coord[1]]
        return coord
    else:
        cache[key] = None
        return None


def geocode_all(entries: list[dict], cache: dict) -> list[dict]:
    """批量地理编码"""
    total = len(entries)
    print(f"\n{'='*60}")
    print(f"  开始地理编码 (后端: {PROVIDER}) - 共 {total} 个地址")
    print(f"{'='*60}\n")

    results = []
    pad = len(str(total))

    for i, entry in enumerate(entries):
        addr = entry.get("address", "").strip()
        province = entry.get("province", "")
        city = entry.get("city", "")
        company = entry.get("company", "") or ""

        key = cache_key(addr, province, city, PROVIDER)
        num = f"[{i+1:>{pad}}/{total}]"

        if key in cache and cache[key] is not None:
            lat, lon = cache[key]
            results.append({**entry, "lat": lat, "lon": lon})
            print(f"  {num} {company[:24]:24s} -> OK (cache)")
            continue

        coord = geocode_address(addr, province, city, cache)
        if coord:
            lat, lon = coord
            results.append({**entry, "lat": lat, "lon": lon})
            print(f"  {num} {company[:24]:24s} -> OK")
        else:
            print(f"  {num} {company[:24]:24s} -> 跳过: 地址解析失败")

        time.sleep(RATE_LIMIT)

    print(f"\n  完成！成功编码 {len(results)}/{total} 个地址\n")
    return results


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

        features.append({
            "lat": e["lat"],
            "lon": e["lon"],
            "name": e.get("company", ""),
            "address": e.get("address", ""),
            "isFactory": is_factory,
            "color": color,
            "size": marker_size,
            "opacity": opacity,
        })

    features_json = json.dumps(features, ensure_ascii=False)

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
    var popupHtml = '<div class="popup-content">'
      + '<h3>' + f.name + '</h3>'
      + '<div class="popup-address">' + f.address + '</div>'
      + '<span class="popup-tag ' + tagClass + '">' + tagLabel + '</span>'
      + '</div>';

    marker.bindPopup(popupHtml, {{
      closeButton: true,
      maxWidth: 280,
    }});

    markers.addLayer(marker);
  }});

  map.addLayer(markers);

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

    # 3. 地理编码（带缓存）
    cache = load_cache(cache_path)
    cached_count = sum(1 for v in cache.values() if v is not None)
    print(f"   缓存命中: {cached_count} 条")
    geocoded = geocode_all(entries, cache)
    save_cache(cache, cache_path)

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
