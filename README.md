# Stock One-Pager

一键生成美观、交互式的股票研究 One-Pager（HTML 格式），支持 **美股 / A股 / 港股**。

**[查看 NVIDIA (NVDA) 示例 →](https://billyoftea.github.io/stock-onepager/examples/NVDA_onepager.html)**

## 功能

- **多市场支持** — 美股 (yfinance + SEC EDGAR)、A股 (akshare)、港股 (yfinance)
- **日历年 (CY) 财务数据** — 自动将财年 (FY) 转换为日历年
- **ECharts 交互图表** — 悬停查看数值、图例筛选、股价拖拽缩放
- **6 大模块** — 业务拆解、估值定位、财务核心、投资框架、风险 & 催化剂、股价走势
- **单 HTML 文件** — 无需服务器，浏览器直接打开

## 快速开始

```bash
pip install yfinance akshare requests

# 美股
python scripts/fetch_data.py NVDA | python scripts/build_onepager.py --stdin

# A股
python scripts/fetch_data.py 600036 | python scripts/build_onepager.py --stdin

# 港股
python scripts/fetch_data.py 0700.HK | python scripts/build_onepager.py --stdin
```

生成的 HTML 文件在 `./out/` 目录下。

## 高级用法

```bash
# 指定市场
python scripts/fetch_data.py 600036 --market cn | python scripts/build_onepager.py --stdin

# 从 JSON 文件生成
python scripts/fetch_data.py AAPL > data.json
python scripts/build_onepager.py --data data.json

# 自定义输出目录
python scripts/build_onepager.py --data data.json --output-dir ./reports
```

## 项目结构

```
stock-onepager/
├── scripts/
│   ├── fetch_data.py      # 多市场数据拉取
│   └── build_onepager.py  # 数据填充模板，生成 HTML
├── template.html           # HTML 模板（{{PLACEHOLDER}} 格式）
├── examples/
│   └── NVDA_onepager.html  # NVIDIA 示例（含 ECharts 交互图表）
└── README.md
```

## 数据源

| 市场 | 来源 | 说明 |
|------|------|------|
| 美股 | yfinance, SEC EDGAR | 免费无需 API Key |
| A股 | akshare (Sina/THS/Baidu) | 免费无需 API Key，无需代理 |
| 港股 | yfinance | 免费 |

## 依赖

- Python 3.10+
- yfinance
- akshare (A股)
- requests

## License

MIT
