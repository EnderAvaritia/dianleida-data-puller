# 店雷达数据拉取

自动从 [店雷达 (dianleida.net)](https://www.dianleida.net/) 拉取商品、店铺和竞品数据的工具。

## 原理

通过 Playwright 无头浏览器 + 持久化 Cookie 登录店雷达 Web 端，利用其内部 API (`api.dianleida.net`) 批量拉取数据。Cookie 持久化后无需重复登录。

## 快速开始

### 1. 安装

```bash
# 创建虚拟环境
python -m venv venv

# 激活并安装依赖
venv\Scripts\activate
pip install playwright requests
playwright install chromium
```

### 2. 登录

```bash
venv\Scripts\python.exe login.py
```

会弹出浏览器窗口，手动完成登录后 Cookie 自动保存到 `cookies.json`。后续运行自动加载 Cookie，无需重复登录。

### 3. 验证登录状态

```bash
venv\Scripts\python.exe cookies_verify.py
```

### 4. 拉取数据

```bash
# 搜索商品，默认 1 页
venv\Scripts\python.exe fetch_products.py "关键词"

# 翻页 + 自定义排序
venv\Scripts\python.exe fetch_products.py "女装" --pages 5 --size 50 --sort saleCount7d
```

数据导出到 `output/` 目录（JSON + CSV）。

---

## 脚本参数详解

### `login.py` — 登录

**参数**: 无

首次运行弹出浏览器窗口，手动扫码或账号密码登录；已有 `cookies.json` 时自动加载并验证，过期则重新弹出登录窗口。

| 行为 | 说明 |
|------|------|
| 首次运行 | 打开浏览器 → 加载店雷达首页 → 自动点击"登录"按钮 → 等待你手动扫码/输入账号密码 → 登录成功后自动保存 Cookie |
| 已有 Cookie | 加载 `cookies.json` → 验证是否有效 → 有效则跳过，无效则重新登录 |
| 登录成功后 | 自动跳转到选品库页面，浏览器保持打开，方便你抓包观察 API |
| 退出 | 按 `Ctrl+C` 关闭浏览器 |

### `cookies_verify.py` — 验证 Cookie 有效性

**参数**: 无

无头模式快速检测 Cookie 是否过期，不弹出浏览器窗口。

| 输出 | 含义 |
|------|------|
| `[OK] Cookie 有效，已登录状态` | 页面检测到"工作台"，Cookie 正常 |
| `[FAIL] Cookie 已过期` | Cookie 失效，需重新运行 `login.py` |
| `[FAIL] cookies.json 不存在` | 还没登录过 |

### `fetch_products.py` — 拉取数据（核心脚本）

```bash
venv\Scripts\python.exe fetch_products.py [关键词] [选项]
```

#### 位置参数

| 参数 | 默认值 | 说明 |
|------|--------|------|
| `keyword` | `女装` | 搜索关键词，支持商品名、店铺名等 |

#### 选项参数

| 参数 | 默认值 | 说明 |
|------|--------|------|
| `--pages` | `1` | 拉取页数。每页最多 200 条，5 页 = 最多 1000 条 |
| `--size` | `30` | 每页条数，最大 `200` |
| `--sort` | `bookedCount7dGrowthRate` | 排序字段，见下表 |

#### `--sort` 可选值

| 参数值 | 含义 | 说明 |
|--------|------|------|
| `bookedCount7dGrowthRate` | 7日订单增长率 | **默认排序**，反映近期增长趋势 |
| `bookedCount7d` | 7日订单数 | 近 7 天下单量 |
| `dayBookedCount` | 日订单数 | 当天下单量 |
| `saleCount7d` | 7日销量 | 近 7 天销量（件数） |
| `saleVolume7d` | 7日销售额 | 近 7 天销售额（金额） |
| `offerRepurchaseRate` | 复购率 | 商品复购比例 |
| `beFavedCount` | 收藏人气 | 收藏数 |
| `offerCreateTime` | 上架时间 | 最新上架优先 |

#### 实际例子

```bash
# 搜索"防晒衣"1页，每页50条，按7日销量排序
venv\Scripts\python.exe fetch_products.py "防晒衣" --size 50 --sort saleCount7d

# 搜索"男鞋"翻10页，按7日销售额排序
venv\Scripts\python.exe fetch_products.py "男鞋" --pages 10 --size 50 --sort saleVolume7d

# 搜索"宠物用品"按复购率排序
venv\Scripts\python.exe fetch_products.py "宠物用品" --sort offerRepurchaseRate

# 搜索"收纳盒"按上架时间排序（找新品）
venv\Scripts\python.exe fetch_products.py "收纳盒" --sort offerCreateTime

# 搜索"运动服"拉3页，默认排序（7日订单增长率）
venv\Scripts\python.exe fetch_products.py "运动服" --pages 3
```

#### 输出文件

| 文件 | 格式 | 说明 |
|------|------|------|
| `output/{关键词}.json` | JSON | 完整原始数据，包含所有字段 |
| `output/{关键词}.csv` | CSV | 展平的核心字段，可用 Excel/WPS 打开 |

---

## API 字段详解

### 字段列表

每条商品返回 50+ 字段。以下按用途分组说明：

#### 基础信息

| 字段 | 类型 | 说明 |
|------|------|------|
| `offerId` | string | **商品唯一 ID**，可用于去重或后续详情查询 |
| `subject` | string | 商品标题 |
| `title` | string | 同上，部分场景用此字段 |
| `image` | string | 商品主图 URL，可直接浏览器打开 |
| `levelName` | string | 类目路径，例如 `"女装/连衣裙/夏季"` |

#### 价格

| 字段 | 类型 | 说明 |
|------|------|------|
| `price` | number | 批发价（元） |
| `consignPrice` | number | 代发价（元），通常比批发价略高 |
| `mixWholePrice` | number | 混批价（元） |
| `mixDealPrice` | number | 混批成交价（元） |

#### 订单 & 销量

| 字段 | 类型 | 说明 |
|------|------|------|
| `bookedCount` | number | **累计订单数**（历史总订单） |
| `saleCount` | number | **累计销量**（历史总销量，件数） |
| `dayBookedCount` | number | **日订单数**（今天） |
| `daySaleQuantity` | number | **日销量**（今天，件数） |
| `bookedCount7d` | number | **7日订单数**（近 7 天下单量） |
| `saleQuantity7d` | number | **7日销量**（近 7 天件数） |
| `salesVolume7d` | number | **7日销售额**（近 7 天金额，元） |
| `bookedCount30d` | number | **30日订单数** |
| `saleQuantity30d` | number | **30日销量** |
| `salesVolume30d` | number | **30日销售额** |

#### 趋势 & 复购

| 字段 | 类型 | 说明 |
|------|------|------|
| `bookedCount7dGrowthRate` | number | **7日订单增长率**（小数，如 0.25 = 25%） |
| `bookedCount7dGrowth` | number | 7日订单增长量 |
| `offerRepurchaseRate` | number | 复购率（小数，如 0.35 = 35%） |
| `saleQuantity30dStr` | string | **30日每日销量趋势**（JSON 字符串），解析后为长度 30 的数组 |
| `salVolume30dStr` | string | 30日每日销售额趋势（JSON 字符串） |

#### 供应商信息

| 字段 | 类型 | 说明 |
|------|------|------|
| `sellerAccount` | string | 供应商名称（店铺名） |
| `company` | string | 公司名称 |
| `province` | string | 省份 |
| `city` | string | 城市 |
| `tpYear` | number | 开店年限 |
| `comprehensiveScore` | number | 店铺综合评分 |
| `serviceScore` | number | 服务评分 |
| `logisticsScore` | number | 物流评分 |

#### 其他

| 字段 | 类型 | 说明 |
|------|------|------|
| `offerCreateTime` | string | 上架时间，格式 `"2024-06-15 10:30:00"` |
| `deliveryTime` | number | 发货时效（小时），如 `48` = 48 小时内发货 |
| `beFavedCount` | number | 收藏人气 |
| `unit` | string | 单位，如 `"件"`、`"个"` |
| `minOrderQuantity` | number | 起批量 |
| `freightType` | number | 运费类型 |
| `qualityScore` | number | 商品质量分 |

### 字段使用场景

| 你想分析什么 | 用哪些字段 |
|-------------|-----------|
| **热销爆品** | `saleQuantity7d`（7日销量）、`saleVolume7d`（7日销售额） |
| **增长趋势** | `bookedCount7dGrowthRate`（增长率）、`saleQuantity30dStr`（30日趋势） |
| **高复购商品** | `offerRepurchaseRate`（复购率） |
| **新品机会** | `offerCreateTime`（上架时间）+ `bookedCount7dGrowthRate`（增长率） |
| **供应商评估** | `sellerAccount` + `tpYear` + `comprehensiveScore` |
| **代发选品** | `consignPrice`（代发价）+ `deliveryTime`（发货时效） |
| **地域分析** | `province` + `city` |
| **累计表现** | `bookedCount`（累计订单数）+ `saleCount`（累计销量） |

### 代码中如何用这些字段

```python
from api_client import DianLeidaClient

client = DianLeidaClient()
client.start()

result = client.search_products("连衣裙", page=1, page_size=10, sort_field="saleCount7d")
items = result["result"]["list"]

for item in items:
    print(f"{item['offerId']} | {item['subject'][:30]}")
    print(f"  价格: {item.get('price')}元 / 代发: {item.get('consignPrice')}元")
    print(f"  7日销量: {item.get('saleQuantity7d')}  7日订单: {item.get('bookedCount7d')}")
    print(f"  7日销售额: {item.get('salesVolume7d')}元  复购率: {item.get('offerRepurchaseRate')}")

    # 解析30日每日销量趋势
    trend_str = item.get('saleQuantity30dStr')
    if trend_str:
        import json
        trend = json.loads(trend_str)  # 长度30的数组
        print(f"  近30日趋势: {trend[-7:]}")  # 最近7天

    print(f"  店铺: {item.get('sellerAccount')} | {item.get('province')}{item.get('city')}")
    print(f"  上架: {item.get('offerCreateTime')}  发货: {item.get('deliveryTime')}h")
    print()
```

---

## API 客户端（`api_client.py`）参考

### `DianLeidaClient`

```python
client = DianLeidaClient(cookie_path="cookies.json")
client.start()                                    # 启动浏览器
client.is_logged_in() -> bool                     # 验证登录状态
client.search_products(
    keyword="女装",                               # 搜索关键词
    page=1,                                       # 页码
    page_size=30,                                 # 每页条数（最大200）
    sort_field="bookedCount7dGrowthRate",          # 排序字段
    sort_type="desc",                              # 排序方向 desc/asc
    days=30,                                      # 数据范围天数
) -> dict                                         # 返回API响应JSON
client.stop()                                     # 关闭浏览器
```

也支持 `with` 语句自动管理生命周期：

```python
with DianLeidaClient() as client:
    result = client.search_products("T恤", page=1)
```

### `SORT_OPTIONS` 快捷别名

`api_client.py` 内置了一组排序别名字典 `SORT_OPTIONS`，你也可以这样用：

```python
from api_client import DianLeidaClient, SORT_OPTIONS

client = DianLeidaClient()
client.start()
result = client.search_products("女装", sort_field=SORT_OPTIONS["7d_sales"])
```

| 别名 | 对应值 | 说明 |
|------|--------|------|
| `7d_growth` | `bookedCount7dGrowthRate` | 7日订单增长率 |
| `7d_orders` | `bookedCount7d` | 7日订单数 |
| `daily_orders` | `dayBookedCount` | 日订单数 |
| `7d_sales` | `saleCount7d` | 7日销量 |
| `7d_revenue` | `saleVolume7d` | 7日销售额 |
| `repurchase` | `offerRepurchaseRate` | 复购率 |
| `popularity` | `beFavedCount` | 收藏人气 |
| `newest` | `offerCreateTime` | 上架时间 |
| `price_asc` | `beginPrice` | 价格升序 |

---

## 项目结构

```
├── login.py              # 登录脚本（手动扫码，保存 Cookie）
├── api_client.py          # API 客户端封装（DianLeidaClient）
├── fetch_products.py      # 数据拉取工具（命令行入口）
├── cookies_verify.py      # Cookie 有效性检测
├── _explore.py            # （内部测试）
├── cookies.json           # 持久化 Cookie（已 gitignore）
├── output/                # 导出数据目录（JSON + CSV）
└── venv/                  # Python 虚拟环境
```

## Cookie 有效期

- Cookie 会过期（店雷达 Token 有效期约 30 天）
- `cookies_verify.py` 可以检测是否仍有效
- 过期后重新运行 `login.py` 扫码登录即可
