#!/usr/bin/env python3
"""
fetch_data.py — 多市场统一数据拉取 (美股 / A股 / 港股)
用法: python fetch_data.py <ticker> [--market auto|us|cn|hk] [--output json]

市场自动识别:
  NVDA, AAPL, TSLA        → US (yfinance + SEC EDGAR)
  0700.HK, 9988.HK        → HK (yfinance)
  600036, 000001, sh600036 → A股 (akshare)

输出: JSON, 包含模板所需的全部字段
"""

import sys
import json
import math
import argparse
import os
from datetime import datetime, timedelta

sys.stdout.reconfigure(encoding='utf-8')
sys.stderr.reconfigure(encoding='utf-8')


def parse_cn_amount(val) -> float | None:
    """解析中文财务数值: '4.82亿'→482000000, '66.84%'→0.6684, '0.1200'→0.12"""
    s = str(val).strip()
    if not s or s in ('nan', 'False', ''):
        return None
    try:
        # 百分比
        if s.endswith('%'):
            return float(s.replace('%', '')) / 100
        # 亿
        if '亿' in s:
            return float(s.replace('亿', '')) * 1e8
        # 万
        if '万' in s:
            return float(s.replace('万', '')) * 1e4
        # 纯数字
        return float(s)
    except (ValueError, TypeError):
        return None


def str_to_float(val) -> float | None:
    """安全转浮点数"""
    if val is None:
        return None
    try:
        return float(val)
    except (ValueError, TypeError):
        return None


# ============================================================
#  市场识别
# ============================================================

def detect_market(ticker: str) -> str:
    """根据代码格式自动识别市场"""
    t = ticker.upper().strip()

    # HK: 数字.HK 格式
    if '.HK' in t:
        return 'hk'

    # A股: 6位数字 或 sh/sz 前缀
    if t.startswith('SH') or t.startswith('SZ'):
        return 'cn'
    if t.isdigit() and len(t) == 6:
        return 'cn'

    # 美股: 纯字母（1-5位）
    if t.replace('.', '').replace('-', '').isalpha():
        return 'us'

    return 'us'


# ============================================================
#  数据拉取: 美股
# ============================================================

def fetch_us(ticker: str, proxy: str = None) -> dict:
    """美股: yfinance + SEC EDGAR"""
    import yfinance as yf
    import requests

    if proxy:
        os.environ['HTTPS_PROXY'] = f'http://{proxy}'

    stock = yf.Ticker(ticker)
    info = stock.info
    income = stock.financials  # 年度
    balance = stock.balance_sheet
    cashflow = stock.cashflow

    # --- 基本信息 ---
    currency = info.get('financialCurrency', 'USD')
    result = {
        'ticker': ticker,
        'market': 'US',
        'company_name': info.get('longName') or info.get('shortName', ticker),
        'industry': info.get('industry', ''),
        'currency': currency,
        'currency_unit': '$M' if max(1, info.get('totalRevenue', 1) or 1) < 1e11 else '$B',
        'price': info.get('currentPrice'),
        'market_cap': info.get('marketCap'),
        'pe_ttm': info.get('trailingPE'),
        'pe_forward': info.get('forwardPE'),
        'pb': info.get('priceToBook'),
        'ps': info.get('priceToSales'),
        '52w_high': info.get('fiftyTwoWeekHigh'),
        '52w_low': info.get('fiftyTwoWeekLow'),
        'shares_outstanding': info.get('sharesOutstanding'),
        'beta': info.get('beta'),
        'dividend_yield': info.get('dividendYield'),
        'data': {},
    }

    # --- 损益表 ---
    field_map = {
        'Total Revenue': 'revenue',
        'Cost Of Revenue': 'cogs',
        'Gross Profit': 'gross_profit',
        'Operating Revenue': 'operating_revenue',
        'Operating Expense': 'opex',
        'Operating Income': 'ebit',
        'Net Income': 'net_income',
        'Research And Development': 'rd',
        'Selling General And Administration': 'sga',
        'Interest Expense': 'interest_expense',
        'Tax Provision': 'tax',
        'Diluted EPS': 'eps_diluted',
        'EBITDA': 'ebitda',
    }

    for col in income.columns:
        year_label = f"{col.year}A"
        row = {}
        for yf_name, key in field_map.items():
            if yf_name in income.index:
                val = income.loc[yf_name, col]
                if hasattr(val, 'item'):
                    val = val.item()
                if isinstance(val, float) and math.isnan(val):
                    val = None
                row[key] = val if val is None else (float(val) if isinstance(val, (int, float)) else None)
        if any(v is not None for v in row.values()):
            result['data'][year_label] = row

    # 排序, 保留近5年
    result['data'] = dict(sorted(result['data'].items()))
    all_years = list(result['data'].keys())
    if len(all_years) > 5:
        result['data'] = {k: result['data'][k] for k in all_years[-5:]}

    # --- 计算利润率和增速 ---
    for i, year in enumerate(sorted(result['data'].keys())):
        d = result['data'][year]
        rev = d.get('revenue')
        if rev and rev != 0:
            d['gross_margin'] = round(d['gross_profit'] / rev, 4) if d.get('gross_profit') else None
            d['ebit_margin'] = round(d['ebit'] / rev, 4) if d.get('ebit') else None
            d['net_margin'] = round(d['net_income'] / rev, 4) if d.get('net_income') else None
            d['rd_ratio'] = round(d['rd'] / rev, 4) if d.get('rd') else None
        if i > 0:
            prev_rev = result['data'][sorted(result['data'].keys())[i-1]].get('revenue')
            if prev_rev and prev_rev != 0 and rev:
                d['revenue_growth'] = round((rev - prev_rev) / prev_rev, 4)

    # --- 估值历史 (pe_history) ---
    try:
        hist = stock.history(period='5y')
        if not hist.empty:
            # 按年取 PE 近似值 (Close / EPS粗略)
            hist['Year'] = hist.index.year
            result['pe_history'] = {}
            # 用收盘价和 annual EPS 估算
    except Exception:
        result['pe_history'] = {}

    # --- 补充 EDGAR ---
    try:
        headers = {'User-Agent': 'coverage-model@example.com'}
        proxies = {'https': f'http://{proxy}', 'http': f'http://{proxy}'} if proxy else {}
        resp = requests.get('https://www.sec.gov/files/company_tickers.json',
                            headers=headers, proxies=proxies, timeout=30)
        tickers_data = resp.json()
        cik = None
        for v in tickers_data.values():
            if v.get('ticker', '').upper() == ticker.upper():
                cik = str(v['cik_str']).zfill(10)
                break
        if cik:
            facts_url = f"https://data.sec.gov/api/xbrl/companyfacts/CIK{cik}.json"
            resp = requests.get(facts_url, headers=headers, proxies=proxies, timeout=30)
            facts = resp.json()
            us_gaap = facts.get('facts', {}).get('us-gaap', {})
            for field in ['Revenues', 'RevenueFromContractWithCustomerExcludingAssessedTax']:
                if field in us_gaap:
                    units = us_gaap[field].get('units', {}).get('USD', [])
                    result['edgar_revenue'] = {}
                    for e in units:
                        if e.get('form') == '10-K' and e.get('frame', '').startswith('CY') and 'Q' not in e.get('frame', ''):
                            result['edgar_revenue'][f"{e['frame'][2:6]}A"] = e['val']
                    break
    except Exception:
        pass

    return result


# ============================================================
#  数据拉取: A股
# ============================================================

def fetch_cn(ticker: str, proxy: str = None) -> dict:
    """A股: akshare"""
    try:
        import akshare as ak
    except ImportError:
        print("请先安装 akshare: pip install akshare", file=sys.stderr)
        sys.exit(1)

    # akshare 用国内API，需清除代理
    saved_proxy = os.environ.pop('HTTPS_PROXY', None)
    os.environ.pop('HTTP_PROXY', None)

    # 标准化为纯6位代码
    code = ticker.lower().replace('sh', '').replace('sz', '').strip()
    ticker_clean = f"sh{code}" if code.startswith(('6', '9')) else f"sz{code}"

    result = {
        'ticker': ticker,
        'market': 'CN',
        'company_name': '',
        'industry': '',
        'currency': 'CNY',
        'currency_unit': '¥亿',
        'price': None,
        'market_cap': None,
        'pe_ttm': None,
        'pb': None,
        'ps': None,
        'data': {},
    }

    try:
        # 个股基本信息 (两种 API 兜底)
        info_dict = {}
        try:
            info_df = ak.stock_individual_info_em(symbol=code)
            if not info_df.empty:
                info_dict = dict(zip(info_df['item'], info_df['value']))
        except Exception:
            pass

        # 兜底1: Sina 实时行情 (比akshare东财API更稳定)
        if not info_dict:
            try:
                import requests
                sina_code = f"sh{code}" if code.startswith(('6', '9')) else f"sz{code}"
                resp = requests.get(f'https://hq.sinajs.cn/list={sina_code}',
                                    headers={'Referer': 'https://finance.sina.com.cn'}, timeout=10)
                resp.encoding = 'gbk'
                parts = resp.text.split('"')[1].split(',')
                if len(parts) >= 30:
                    info_dict = {
                        '股票简称': parts[0],
                        '最新价': parts[3],
                        '昨收盘': parts[2],
                        '最高价': parts[4],
                        '最低价': parts[5],
                    }
            except Exception:
                pass

        if info_dict:
            result['company_name'] = info_dict.get('股票简称', ticker)
            result['price'] = str_to_float(info_dict.get('最新价'))
            result['market_cap'] = str_to_float(info_dict.get('总市值'))
            result['pe_ttm'] = str_to_float(info_dict.get('市盈率-动态'))
            result['pb'] = str_to_float(info_dict.get('市净率'))
            result['industry'] = info_dict.get('行业', '')
    except Exception as e:
        print(f"  [akshare] 基本信息获取失败: {e}", file=sys.stderr)

    try:
        # 财务数据 (同花顺)
        fin_df = ak.stock_financial_abstract_ths(symbol=code, indicator="按年度")
        if not fin_df.empty:
            for _, row in fin_df.iterrows():
                date_str = str(row.get('报告期', ''))
                if not date_str or date_str == 'nan':
                    continue
                try:
                    year = int(date_str[:4])
                except ValueError:
                    continue
                year_label = f"{year}A"

                if year_label not in result['data']:
                    result['data'][year_label] = {}

                d = result['data'][year_label]
                # 字段映射 (同花顺列名)
                indicators = {
                    '营业总收入': 'revenue',
                    '营业收入': 'revenue',
                    '净利润': 'net_income',
                    '营业总成本': 'opex',
                    '营业成本': 'cogs',
                    '营业利润': 'ebit',
                    '基本每股收益': 'eps_basic',
                    '每股净资产': 'book_value_per_share',
                    '每股经营现金流': 'ocf_per_share',
                    '销售净利率': 'net_margin_raw',
                    '净资产收益率': 'roe',
                    '资产负债率': 'debt_ratio',
                }
                for cn_name, key in indicators.items():
                    val = row.get(cn_name)
                    if val is None or str(val) in ('nan', 'False', ''):
                        continue
                    # 解析带单位的数值 (如 "4.82亿", "72.64亿", "0.1200", "6.63%")
                    try:
                        num = parse_cn_amount(val)
                        if num is not None:
                            d[key] = num
                    except (ValueError, TypeError):
                        pass
    except Exception as e:
        print(f"  [akshare] 财务数据获取失败: {e}", file=sys.stderr)

    # 计算利润率和增速
    years_sorted = sorted(result['data'].keys())
    for i, year in enumerate(years_sorted):
        d = result['data'][year]
        rev = d.get('revenue')
        if rev and rev != 0:
            if d.get('cogs'):
                d['gross_profit'] = rev - d['cogs']
                d['gross_margin'] = round(d['gross_profit'] / rev, 4)
            d['ebit_margin'] = round(d['ebit'] / rev, 4) if d.get('ebit') else None
            ni = d.get('net_income_parent') or d.get('net_income')
            d['net_margin'] = round(ni / rev, 4) if ni else None
        if i > 0:
            prev = result['data'][years_sorted[i-1]].get('revenue')
            if prev and prev != 0 and rev:
                d['revenue_growth'] = round((rev - prev) / prev, 4)

    # 保留近5年
    if len(years_sorted) > 5:
        result['data'] = {k: result['data'][k] for k in years_sorted[-5:]}

    return result


# ============================================================
#  数据拉取: 港股
# ============================================================

def fetch_hk(ticker: str, proxy: str = None) -> dict:
    """港股: yfinance (XXXX.HK 格式)"""
    if proxy:
        os.environ['HTTPS_PROXY'] = f'http://{proxy}'

    result = fetch_us(ticker, proxy)  # yfinance 逻辑复用
    result['market'] = 'HK'
    result['currency'] = 'HKD'
    result['currency_unit'] = 'HK$M'

    # 港股 yfinance info 的字段名稍有不同
    import yfinance as yf
    stock = yf.Ticker(ticker)
    info = stock.info
    result['company_name'] = info.get('longName') or info.get('shortName', ticker)
    result['industry'] = info.get('industry', '')
    result['pe_ttm'] = info.get('trailingPE')
    result['pb'] = info.get('priceToBook')

    return result


# ============================================================
#  主入口
# ============================================================

def main():
    parser = argparse.ArgumentParser(description='多市场统一数据拉取')
    parser.add_argument('ticker', help='股票代码')
    parser.add_argument('--market', choices=['auto', 'us', 'cn', 'hk'], default='auto')
    parser.add_argument('--proxy', default='127.0.0.1:7890')
    parser.add_argument('--output', choices=['json', 'csv'], default='json')
    args = parser.parse_args()

    market = args.market if args.market != 'auto' else detect_market(args.ticker)
    print(f"市场: {market.upper()} | 代码: {args.ticker}", file=sys.stderr)

    if market == 'us':
        result = fetch_us(args.ticker, args.proxy)
    elif market == 'cn':
        result = fetch_cn(args.ticker, args.proxy)
    elif market == 'hk':
        result = fetch_hk(args.ticker, args.proxy)
    else:
        print(f"无法识别市场: {args.ticker}", file=sys.stderr)
        sys.exit(1)

    # JSON 输出
    print(json.dumps(result, ensure_ascii=False, indent=2, default=str))

    # 摘要
    years = sorted(result['data'].keys())
    print(f"\n=== {result['company_name']} ({result['ticker']}) ===", file=sys.stderr)
    print(f"行业: {result['industry']} | 货币: {result['currency']}", file=sys.stderr)
    if result.get('price'):
        print(f"股价: {result['price']} | PE: {result.get('pe_ttm')} | PB: {result.get('pb')}", file=sys.stderr)
    print(f"数据年度: {', '.join(years)}", file=sys.stderr)


if __name__ == '__main__':
    main()
