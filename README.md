# 店雷达数据采集 & 商家地图标记

一站式工具：从 [店雷达 (dianleida.net)](https://www.dianleida.net/) 拉取商品/商家数据，然后生成交互式地图标记店铺位置。

## 项目结构

```
├── login.py              # 登录（扫码 → 保存 Cookie）
├── api_client.py          # API 客户端
├── fetch_products.py      # 数据拉取工具（商品/商家）
├── fetch_all_shops.py     # 按类目批量采集商家（突破免费版限制）
├── cookies_verify.py      # Cookie 有效性检测
├── generate_map.py        # 地图标记生成器（将 CSV 地址 → 交互式地图）
├── config.example.json    # 地图工具配置示例（复制为 config.json 使用）
├── cookies.json           # 持久化 Cookie (已 gitignore)
├── config.json            # 地图工具配置文件（含 API Key, 已 gitignore）
├── output/                # 导出数据 & 地图输出目录
│   ├── shops_江苏常州.json / .csv    # 店雷达采集结果
│   ├── changzhou_shops_map.html      # 生成的交互式地图
│   ├── geocode_cache.json            # 地理编码缓存
│   ├── categories.json               # 类目列表缓存
│   └── ...
└── README.md
```

## 快速开始

```bash
# 1. 安装
python -m venv venv
venv\Scripts\activate
pip install playwright
playwright install chromium

# 2. 登录（首次需扫码）
venv\Scripts\python.exe login.py

# 3. 搜商品
venv\Scripts\python.exe fetch_products.py product "女装" --pages 3

# 4. 拉商家
venv\Scripts\python.exe fetch_products.py shop --pages 2
```

## 命令说明

### 商品搜索

```bash
venv\Scripts\python.exe fetch_products.py product "关键词" [选项]
```

选项:
- `--pages N` — 拉取 N 页 (默认 1)
- `--size N` — 每页 N 条 (默认 30, 最大 200)
- `--sort FIELD` — 排序字段
- `--debug` — 打开浏览器窗口（调试用，可见弹窗和操作过程）

排序字段:
| 参数 | 说明 |
|------|------|
| `bookedCount7dGrowthRate` | 7日订单增长率 (默认) |
| `bookedCount7d` | 7日订单数 |
| `saleCount7d` | 7日销量 |
| `saleVolume7d` | 7日销售额 |
| `offerRepurchaseRate` | 复购率 |
| `offerCreateTime` | 上架时间 |

### 商家/供应商拉取

支持按**省份/城市**筛选，自动翻页拉取所有数据。

```bash
# 拉取全国商家
venv\Scripts\python.exe fetch_products.py shop --pages 5

# 拉取浙江省所有商家
venv\Scripts\python.exe fetch_products.py shop --province 浙江 --pages 0

# 拉取杭州市商家
venv\Scripts\python.exe fetch_products.py shop --province 浙江 --city 杭州 --pages 0
```

选项:
- `--province` — 省份过滤 (如 "浙江", "广东")。使用 `--city` 时必须指定
- `--city` — 城市过滤 (如 "杭州", "常州")，必须配合 `--province`
- `--pages N` — 拉取 N 页; **`--pages 0` = 所有页**
- `--size N` — 每页 N 条 (默认 100, 最大 200)
- `--sort FIELD` — 排序字段
- `--from-page N` — 起始页码（跳过前 N-1 页）
- `--resume` — **断点续传**，从上次中断处继续
- `--debug` — 打开浏览器窗口（调试用）

商家排序字段:
| 参数 | 说明 |
|------|------|
| `bookedCount30d` | 30日订单数 (默认) |
| `saleQuantity30d` | 30日销量 |
| `salesVolume30d` | 30日销售额 |

每条商家包含: 公司名、所在地(省/市)、诚信通年限、30日订单/销量/销售额、复购率、响应率等。

### 断点续传

每翻一页自动保存断点到 `output/.shops_{省份}.checkpoint`。遇到风控中断后：

```bash
# 直接恢复，从上一次中断的下一页继续
venv\Scripts\python.exe fetch_products.py shop --province 浙江 --resume
```

### 跳过已拉取的页

```bash
# 从第 50 页开始拉（跳过前 49 页，每页约 2-3 秒）
venv\Scripts\python.exe fetch_products.py shop --province 浙江 --from-page 50 --pages 100

# 配合 --resume 等价于从上次中断处继续
```

## 输出

数据保存到 `output/` 目录:
- `output/{名称}.json` — 完整 JSON
- `output/{名称}.csv` — 展平 CSV

### 商品 CSV 字段说明

| 列名 | 说明 |
|------|------|
| `offerId` | 商品 ID |
| `subject` | 商品标题 |
| `price` | 价格 (¥) |
| `consignPrice` | 一件代发价格 (¥) |
| `bookedCount` | 累计订单数 |
| `saleCount` | 累计销量 |
| `bookedCount7d` | 近 7 日订单数 |
| `saleQuantity7d` | 近 7 日销量 |
| `salesVolume7d` | 近 7 日销售额 (¥) |
| `bookedCount30d` | 近 30 日订单数 |
| `saleQuantity30d` | 近 30 日销量 |
| `salesVolume30d` | 近 30 日销售额 (¥) |
| `offerRepurchaseRate` | 复购率 |
| `sellerAccount` | 卖家账号 |
| `company` | 公司名 |
| `province` | 省份 |
| `city` | 城市 |
| `tpYear` | 诚信通年限 |
| `levelName` | 商品类目 |
| `offerCreateTime` | 上架时间 |
| `image` | 商品主图 URL |

### 商家 CSV 字段说明

| 列名 | 说明 |
|------|------|
| `shopId` | 店铺 ID |
| `company` | 公司名 |
| `sellerAccount` | 卖家 1688 账号 |
| `province` | 省份 |
| `city` | 城市 |
| `address` | 详细地址 |
| `isFactory` | 是否工厂 (true/false) |
| `tpYear` | 诚信通年限 |
| `dayBookedCount` | 日订单数 |
| `daySalesVolume` | 日销售额 (¥) |
| `repeatRate` | 复购率 |
| `wwResponseRate` | 旺旺响应率 |
| `bookedCount30d` | 近 30 日订单数 |
| `saleQuantity30d` | 近 30 日销量 |
| `salesVolume30d` | 近 30 日销售额 (¥) |
| `offerCount` | 在售商品数 |
| `beFavedCount` | 收藏数 |
| `employeesCount` | 员工数 |
| `factorySize` | 工厂面积 (㎡) |
| `productionService` | 生产服务能力 |
| `domainUri` | 店铺链接 |

## 批量采集（按类目拆分）

免费版限制每次查询约 100 条。但 API 支持按**类目（行业）**过滤，不同类目返回不同的商家。

通过遍历 52 个一级类目分别搜索，合并去重后能获取数倍于单次查询的数据：

```bash
# 采集常州所有商家（遍历全部 52 个类目，耗时约 10-20 分钟）
venv\Scripts\python.exe fetch_all_shops.py --province 江苏 --city 常州

# 采集杭州商家
venv\Scripts\python.exe fetch_all_shops.py --province 浙江 --city 杭州

# 从上次中断处自动续传
venv\Scripts\python.exe fetch_all_shops.py --province 江苏 --city 常州 --resume

# 从第 10 个类目开始（手动续传）
venv\Scripts\python.exe fetch_all_shops.py --province 江苏 --city 常州 --from 10

# 只跑前 5 个类目测试
venv\Scripts\python.exe fetch_all_shops.py --province 江苏 --city 常州 --max-cats 5
```

选项:
| 参数 | 说明 |
|------|------|
| `--province` | 省份 |
| `--city` | 城市 |
| `--from N` | 从第 N 个类目开始（手动断点续传） |
| `--resume` | 自动断点续传，从上次中断的类目继续 |
| `--max-cats N` | 最多处理 N 个类目 |

实际效果（常州为例）:
| 方式 | 结果 |
|------|------|
| 单次搜索（默认） | ~100 家 |
| 3 种排序合并 | ~185 家 |
| **52 个类目遍历** | **~2,300 家**（含约 1,300 工厂） |

### 原理

商家搜索 API 的请求 body 中有 `query.categoryIdList` 字段（类目 ID 数组）。
`fetch_all_shops.py` 自动获取 52 个一级类目的 ID，然后对每个类目发起带 `location` + `categoryIdList` 的搜索请求，
最后按 `shopId` 去重合并。

---

## 商家地图标记

将采集到的商家 CSV（含地址、经纬度）生成交互式 Leaflet 地图，标记店铺位置，区分工厂/非工厂。

### 快速开始

```bash
# 安装依赖
pip install -r requirements.txt

# 生成地图（需先配置 API Key）
python generate_map.py
```

打开 `output/changzhou_shops_map.html` 即可查看地图。

### 配置

复制 `config.example.json` 为 `config.json`，填入 API Key：

```bash
cp config.example.json config.json
# 然后编辑 config.json 填入 Key
```

支持三种地理编码后端：

| 服务 | 免费额度 | 推荐场景 | 配置字段 |
|------|---------|---------|---------|
| **天地图** | 10000 次/日 | 国内地址（推荐） | `tianditu_key` |
| **高德地图** | 5000 次/日 | 国内地址（最准） | `amap_key` |
| Nominatim | 无限制（需代理） | 海外地址 | 无需 Key |

### 命令行参数

```bash
# 指定 CSV 文件
python generate_map.py --csv output/my_data.csv

# 指定输出目录和地理编码后端
python generate_map.py --output-dir mymap --provider tianditu

# 使用 Nominatim（免费无需 Key）
python generate_map.py --provider nominatim

# 指定底图风格
python generate_map.py --tile-style gray
```

| 参数 | 说明 | 默认值 |
|---|---|---|
| `--csv` | CSV 文件路径 | `config.json` 中的配置 |
| `--output-dir` | 输出目录 | `output` |
| `--provider` | 编码后端: `amap` / `tianditu` / `nominatim` | `config.json` 中的配置 |
| `--tile-style` | 底图: `clean`(高德路网-中文) / `gray`(浅灰英文) / `tianditu` / `osm` | `clean` |
| `--workers N` | 地理编码线程数（多线程显著提速） | `1`（单线程） |

### 底图风格

| 风格 | 效果 | 国内访问 |
|------|------|---------|
| `clean` ⭐ | 高德路网图（极简，中文标注） | ✅ |
| `gray` | CartoDB Positron（浅灰底色，英文） | ⚠️ 可能需代理 |
| `tianditu` | 天地图彩色矢量+地名标注 | ✅ 需 API Key |
| `osm` | OpenStreetMap 标准地图 | ❌ 可能被屏蔽 |

### 地理缓存

地理编码结果自动缓存到 `output/geocode_cache.json`。第二次运行相同地址直接命中缓存，不会重复请求 API。

缓存命中采用两阶段策略：先**串行扫描缓存**（零开销），只将未命中的地址提交到**线程池**并行请求，缓存命中部分零线程开销。

```bash
# 5 线程并发请求 API（推荐）
python generate_map.py --csv output/shops_常州_全类目.csv --workers 5

# 或设到 config.json： "max_workers": 5
```

### CSV 数据格式

| 列名 | 说明 | 示例 |
|------|------|------|
| `company` | 公司名称 | `常州XX纺织有限公司` |
| `address` | 详细地址（用于地理编码） | `湖塘镇XX路XX号` |
| `province` | 省份 | `江苏` |
| `city` | 城市 | `常州` |
| `isFactory` | 是否为工厂 | `True` / `False` |

采集的商家 CSV 自带以上字段，可直接用于生成地图。

## Cookie 有效期
- 运行 `python cookies_verify.py` 检测
- 过期后重新 `python login.py` 扫码即可
