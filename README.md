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

```bash
venv\Scripts\python.exe fetch_products.py shop --pages 5
```

按 30日订单数排序拉取一手源头工厂/供应商数据，导出 JSON + CSV，含省份分布统计。

每条商家包含: 公司名、所在地(省/市)、诚信通年限、30日订单/销量/销售额、复购率、响应率等。

## 输出

数据保存到 `output/` 目录:
- `output/{关键词}.json` — 完整 JSON
- `output/{关键词}.csv` — 展平 CSV
- `output/shops.json` / `output/shops.csv` — 商家数据

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
