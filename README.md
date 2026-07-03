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

首次使用需要手动扫码/账号登录：

```bash
venv\Scripts\python.exe login.py
```

会弹出浏览器窗口，手动完成登录后 Cookie 自动保存到 `cookies.json`。

下次运行自动加载 Cookie，无需重复登录。

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

## API 说明

### 搜索排序字段

| 参数值 | 说明 |
|--------|------|
| `bookedCount7dGrowthRate` | 7日订单增长率（默认） |
| `bookedCount7d` | 7日订单数 |
| `dayBookedCount` | 日订单数 |
| `saleCount7d` | 7日销量 |
| `saleVolume7d` | 7日销售额 |
| `offerRepurchaseRate` | 复购率 |
| `beFavedCount` | 收藏人气 |
| `offerCreateTime` | 上架时间 |

### 商品字段

每条商品返回 50+ 字段，核心字段：

| 字段 | 说明 |
|------|------|
| `offerId` | 商品 ID |
| `subject` / `title` | 商品标题 |
| `price` | 批发价 |
| `consignPrice` | 代发价 |
| `bookedCount` / `saleCount` | 累计订单数 / 销量 |
| `bookedCount7d` / `saleQuantity7d` | 7日订单数 / 销量 |
| `bookedCount30d` / `saleQuantity30d` | 30日订单数 / 销量 |
| `salesVolume30d` | 30日销售额 |
| `offerRepurchaseRate` | 复购率 |
| `sellerAccount` | 供应商名称 |
| `levelName` | 类目路径 |
| `image` | 商品主图 URL |
| `province` / `city` | 供应商所在地 |
| `daySaleQuantity` / `dayBookedCount` | 日销量 / 日订单数 |
| `saleQuantity30dStr` | 30日每日销量趋势 (JSON) |
| `deliveryTime` | 发货时效（小时） |
| `offerCreateTime` | 上架时间 |

## 项目结构

```
├── login.py              # 登录脚本（手动扫码，保存 Cookie）
├── api_client.py          # API 客户端封装
├── fetch_products.py      # 数据拉取工具（命令行）
├── cookies_verify.py      # Cookie 有效性检测
├── cookies.json           # 持久化 Cookie（已 gitignore）
├── output/                # 导出数据目录
└── venv/                  # Python 虚拟环境
```

## Cookie 有效期

- Cookie 会过期（店雷达 Token 有效期约 30 天）
- `cookies_verify.py` 可以检测是否仍有效
- 过期后重新运行 `login.py` 扫码登录即可
