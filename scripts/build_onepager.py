#!/usr/bin/env python3
"""
build_onepager.py — 将数据填入 HTML 模板, 生成最终 one-pager
用法:
  python build_onepager.py --data data.json                     (从 JSON 文件)
  python fetch_data.py NVDA | python build_onepager.py --stdin  (管道输入)

输出: ./out/<TICKER>_onepager.html
"""

import sys
import json
import argparse
import os
from pathlib import Path
from datetime import datetime

sys.stdout.reconfigure(encoding='utf-8')

# 模板路径（相对于脚本所在目录的上层）
SCRIPT_DIR = Path(__file__).resolve().parent
TEMPLATE_PATH = SCRIPT_DIR.parent / 'template.html'


def fmt_amount(val, unit='M'):
    """格式化金额"""
    if val is None:
        return '—'
    if unit == 'B' or unit == '$B':
        return f"${val/1e9:,.1f}B" if abs(val) >= 1e9 else f"${val/1e6:,.0f}M"
    elif unit == '¥亿':
        return f"¥{val/1e8:,.1f}亿" if abs(val) >= 1e8 else f"¥{val/1e4:,.0f}万"
    else:
        return f"${val/1e6:,.0f}M" if abs(val) >= 1e6 else f"${val:,.0f}"


def fmt_pct(val):
    """格式化百分比"""
    if val is None:
        return '—'
    return f"{val*100:+.1f}%" if val < 0 else f"{val*100:.1f}%"


def build(data: dict, output_dir: str = './out') -> str:
    """填充模板并保存"""

    with open(TEMPLATE_PATH, 'r', encoding='utf-8') as f:
        html = f.read()

    ticker = data.get('ticker', '???')
    company_name = data.get('company_name', ticker)
    market_name = {'US': '美股', 'CN': 'A股', 'HK': '港股'}.get(data.get('market', 'US'), data.get('market', ''))
    currency_unit = data.get('currency_unit', '$M')
    currency = data.get('currency', 'USD')

    # === Header ===
    price = data.get('price')
    market_cap = data.get('market_cap')
    pe_ttm = data.get('pe_ttm')

    # 价格变动
    price_change = ''
    w52h = data.get('52w_high')
    w52l = data.get('52w_low')
    if price and w52h:
        pct_52 = (price / w52h - 1) * 100
        price_change = f"距52周高 {pct_52:+.1f}%"

    # PE 中位数（从 pe_history 计算）
    pe_history = data.get('pe_history', {})
    pe_values = [v for v in pe_history.values() if isinstance(v, (int, float)) and v > 0]
    pe_median = sorted(pe_values)[len(pe_values)//2] if pe_values else (pe_ttm or 0)
    pe_median_str = f"{pe_median:.1f}x" if pe_median else '—'

    # 最新年数据
    years_sorted = sorted(data['data'].keys())
    latest_year = years_sorted[-1].replace('A', '') if years_sorted else '—'
    latest = data['data'][years_sorted[-1]] if years_sorted else {}
    latest_rev = latest.get('revenue')
    latest_rev_str = fmt_amount(latest_rev, currency_unit)
    rev_growth = latest.get('revenue_growth')
    net_margin = latest.get('net_margin')

    # === 替换 ===
    html = html.replace('{{COMPANY_NAME}}', company_name)
    html = html.replace('{{TICKER}}', ticker)
    html = html.replace('{{MARKET}}', market_name)
    html = html.replace('{{INDUSTRY}}', data.get('industry', '—'))
    html = html.replace('{{CURRENCY}}', currency)
    html = html.replace('{{CURRENCY_UNIT}}', currency_unit)
    html = html.replace('{{PRICE}}', f"${price:,.2f}" if price else '—')
    html = html.replace('{{PRICE_CHANGE}}', price_change)
    html = html.replace('{{MARKET_CAP}}', fmt_amount(market_cap, currency_unit) if market_cap else '—')
    html = html.replace('{{PE_TTM}}', f"{pe_ttm:.1f}x" if pe_ttm else '—')
    html = html.replace('{{PE_MEDIAN}}', pe_median_str)
    html = html.replace('{{LATEST_YEAR}}', latest_year)
    html = html.replace('{{LATEST_REVENUE}}', latest_rev_str)
    html = html.replace('{{REVENUE_GROWTH}}', fmt_pct(rev_growth) if rev_growth is not None else '—')
    html = html.replace('{{NET_MARGIN}}', f"{net_margin*100:.1f}%" if net_margin is not None else '—')
    html = html.replace('{{GROSS_MARGIN}}', f"{latest.get('gross_margin', 0)*100:.1f}%" if latest.get('gross_margin') else '—')

    # === 业务描述 ===
    html = html.replace('{{BUSINESS_DESC}}', data.get('business_desc',
        f'{company_name} 是一家{data.get("industry", "综合")}公司。'))

    # === 分部 (Segments) ===
    segments = data.get('segments', {})
    if segments:
        segment_colors = ['#2c5f8a', '#3a7cb8', '#5b9bd5', '#7fb8e8', '#a3d0f0']
        seg_rows = []
        total_rev = sum(segments.values())
        for i, (name, val) in enumerate(segments.items()):
            pct = (val / total_rev * 100) if total_rev > 0 else 0
            color = segment_colors[i % len(segment_colors)]
            seg_rows.append(f'''<li class="segment-item">
              <span class="segment-name">{name}</span>
              <span class="segment-bar-wrap"><span class="segment-bar" style="width:{max(pct,5)}%;background:{color};">{pct:.0f}%</span></span>
              <span class="segment-value">{fmt_amount(val, currency_unit)}</span>
            </li>''')
        html = html.replace('{{SEGMENT_ROWS}}', '\n'.join(seg_rows))
    else:
        html = html.replace('{{SEGMENT_ROWS}}', '<li class="segment-item" style="color:#999;">分部数据待拉取</li>')

    # === 财务数据表 ===
    fin_headers = ''.join(f'<th>{y.replace("A","A")}</th>' for y in years_sorted)
    html = html.replace('{{FIN_HEADERS}}', fin_headers)

    fin_row_defs = [
        ('收入', 'revenue', True),
        ('收入增速', 'revenue_growth', False),
        ('毛利', 'gross_profit', True),
        ('毛利率', 'gross_margin', False),
        ('EBIT', 'ebit', True),
        ('EBIT margin', 'ebit_margin', False),
        ('净利润', 'net_income', True),
        ('净利率', 'net_margin', False),
        ('研发费用率', 'rd_ratio', False),
        ('EPS', 'eps_diluted', True),
    ]

    fin_rows_html = []
    for label, key, is_amount in fin_row_defs:
        cells = [f'<td>{label}</td>']
        for y in years_sorted:
            val = data['data'][y].get(key)
            if val is None:
                cells.append('<td>—</td>')
            elif is_amount:
                cells.append(f'<td>{fmt_amount(val, currency_unit)}</td>')
            else:
                cells.append(f'<td>{fmt_pct(val) if key.endswith("growth") or key.endswith("margin") or key.endswith("ratio") else f"{val:.2f}"}</td>')
        fin_rows_html.append(f'<tr>{"".join(cells)}</tr>')

    html = html.replace('{{FIN_ROWS}}', '\n'.join(fin_rows_html))

    # === 估值 ===
    html = html.replace('{{PE_LOW}}', f"{min(pe_values):.1f}x" if pe_values else '—')
    html = html.replace('{{PE_HIGH}}', f"{max(pe_values):.1f}x" if pe_values else '—')
    html = html.replace('{{PB}}', f"{data.get('pb', 0):.2f}x" if data.get('pb') else '—')
    html = html.replace('{{PS}}', f"{data.get('ps', 0):.2f}x" if data.get('ps') else '—')

    # PE 分位数
    if pe_values and pe_ttm:
        below = sum(1 for v in pe_values if v < pe_ttm)
        percentile = round(below / len(pe_values) * 100)
        html = html.replace('{{PE_PERCENTILE}}', f"{percentile}%")
    else:
        html = html.replace('{{PE_PERCENTILE}}', '—')

    # PE 柱状图
    pe_start_year = years_sorted[0].replace('A', '') if years_sorted else '—'
    pe_mid_year = years_sorted[len(years_sorted)//2].replace('A', '') if years_sorted else '—'
    html = html.replace('{{PE_START_YEAR}}', pe_start_year)
    html = html.replace('{{PE_MID_YEAR}}', pe_mid_year)

    pe_bars_html = ''
    if pe_values:
        max_pe = max(pe_values)
        for i, v in enumerate(pe_values):
            h = max(int(v / max_pe * 55), 3) if max_pe > 0 else 3
            cls = 'current' if i == len(pe_values) - 1 else ''
            pe_bars_html += f'<div class="pe-bar {cls}" style="height:{h}px;" title="{v:.1f}x"></div>'
    html = html.replace('{{PE_BARS}}', pe_bars_html)

    # === 投资框架 ===
    framework = data.get('framework', {})
    framework_items = []
    framework_keys = [
        ('tam', 'TAM / 总可触达市场'),
        ('share', '市占率假设'),
        ('growth_driver', '核心增长驱动'),
        ('margin_outlook', '利润率展望'),
        ('valuation_view', '估值判断'),
        ('moat', '护城河 / 竞争壁垒'),
    ]
    for key, label in framework_keys:
        text = framework.get(key, '待分析')
        framework_items.append(f'''<div class="framework-item">
          <div class="fw-label">{label}</div>
          <div class="fw-text">{text}</div>
        </div>''')
    html = html.replace('{{FRAMEWORK_ITEMS}}', '\n'.join(framework_items))

    # === 风险 & 催化剂 ===
    risks = data.get('risks', ['待分析'])
    catalysts = data.get('catalysts', ['待分析'])

    risk_html = '\n'.join(f'<div class="rc-item">{r}</div>' for r in risks)
    catalyst_html = '\n'.join(f'<div class="rc-item">{c}</div>' for c in catalysts)
    html = html.replace('{{RISK_ITEMS}}', risk_html)
    html = html.replace('{{CATALYST_ITEMS}}', catalyst_html)

    # === Footer ===
    sources = data.get('data_sources', 'yfinance, SEC EDGAR, akshare, 公开市场数据')
    html = html.replace('{{DATA_SOURCES}}', sources)
    html = html.replace('{{GEN_TIME}}', datetime.now().strftime('%Y-%m-%d %H:%M'))

    # === 保存 ===
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    output_path = output_dir / f"{ticker}_onepager.html"
    with open(output_path, 'w', encoding='utf-8') as f:
        f.write(html)

    print(f"One-pager 已生成: {output_path}")
    return str(output_path)


def main():
    parser = argparse.ArgumentParser(description='生成 one-pager HTML')
    parser.add_argument('--data', help='JSON 数据文件路径')
    parser.add_argument('--stdin', action='store_true', help='从标准输入读取 JSON')
    parser.add_argument('--output-dir', default='./out', help='输出目录')
    args = parser.parse_args()

    if args.stdin:
        raw = sys.stdin.read()
        data = json.loads(raw)
    elif args.data:
        with open(args.data, 'r', encoding='utf-8') as f:
            data = json.load(f)
    else:
        print("请指定 --data 或 --stdin", file=sys.stderr)
        sys.exit(1)

    build(data, args.output_dir)


if __name__ == '__main__':
    main()
