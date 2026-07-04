# 店雷达数据拉取

自动从 [店雷达 (dianleida.net)](https://www.dianleida.net/) 拉取商品/商家数据的工具。

通过 Playwright 无头浏览器 + 持久化 Cookie 登录 Web 端，利用内部 API 批量拉取。

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
- `--size N` — 每页 N 条 (默认 30, 最大 50)
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
- `--size N` — 每页 N 条 (默认 100, API 上限 100)
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

## 项目结构

```
├── login.py              # 登录（扫码 → 保存 Cookie）
├── api_client.py          # API 客户端
├── fetch_products.py      # 数据拉取工具（商品/商家）
├── cookies_verify.py      # Cookie 有效性检测
├── cookies.json           # 持久化 Cookie (已 gitignore)
├── output/                # 导出数据目录
└── README.md
```

## Cookie 有效期

- Cookie 约 30 天有效
- 运行 `python cookies_verify.py` 检测
- 过期后重新 `python login.py` 扫码即可
