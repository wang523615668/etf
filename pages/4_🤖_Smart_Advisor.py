import streamlit as st
import pandas as pd
import numpy as np
import os
import sys
import glob
import json
import akshare as ak
from datetime import datetime

# ==========================================
# 1. 基础配置
# ==========================================
st.set_page_config(page_title="全能智能投顾", page_icon="🧠", layout="wide")

CURRENT_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.abspath(os.path.join(CURRENT_DIR, '..'))
DATA_DIR = os.path.join(PROJECT_ROOT, 'index_data')
STATE_FILE = os.path.join(PROJECT_ROOT, 'portfolio_status.json')

TARGET_INDICES = [
    "大盘", "沪深300", "中证500", "创业板指", "上证50",
    "全指医药", "全指消费", "全指信息", "全指金融",
    "养老产业", "中证红利", "中证环保", "中证传媒",
    "证券公司", "中证医疗", "中证白酒"
]

debug_logs = []

# ==========================================
# 2. 核心工具函数
# ==========================================

@st.cache_data(ttl=3600)
def get_bond_yield():
    """联网获取国债收益率"""
    try:
        df = ak.bond_zh_us_rate()
        return float(df['中国国债收益率'].iloc[-1])
    except:
        return 2.20 

def load_portfolio_state():
    """读取持仓"""
    if os.path.exists(STATE_FILE):
        try:
            with open(STATE_FILE, 'r', encoding='utf-8') as f:
                return json.load(f)
        except: return {}
    return {}

def find_csv_file(keyword):
    """查找CSV文件"""
    if not os.path.exists(DATA_DIR):
        debug_logs.append(f"❌ 目录不存在: {DATA_DIR}")
        return None
    pattern = os.path.join(DATA_DIR, f"*{keyword}*.csv")
    files = glob.glob(pattern)
    if not files:
        debug_logs.append(f"⚠️ 未找到: {keyword}")
        return None
    return max(files, key=os.path.getmtime)

def load_and_clean_data(file_path, index_name):
    """
    读取并清洗数据 (统一映射为 pe_percentile)
    """
    try:
        try: df = pd.read_csv(file_path, encoding='utf-8-sig')
        except: df = pd.read_csv(file_path, encoding='gbk')
            
        col_map = {}
        # 优先级匹配
        rules = {
            'pe': ['PE-TTM正数等权', 'PE-TTM', '市盈率TTM', 'PE'],
            'pe_percentile': ['PE-TTM 分位点', 'PE-TTM分位点', '分位点', '百分位'], # 统一键名
            'Date': ['日期', 'Date', 'date'],
            'Close': ['收盘点位', '收盘价', '收盘', 'Close']
        }

        for target, candidates in rules.items():
            for cand in candidates:
                if cand in df.columns:
                    col_map[cand] = target
                    break

        df = df.rename(columns=col_map)
        
        if 'pe' not in df.columns or 'Date' not in df.columns:
            return None, "缺失列(pe/Date)"

        df['Date'] = pd.to_datetime(df['Date'], errors='coerce')
        # 清洗数值
        for col in ['pe', 'pe_percentile', 'Close']:
            if col in df.columns:
                if df[col].dtype == object:
                    df[col] = df[col].astype(str).str.replace(r'[^\d.]', '', regex=True)
                df[col] = pd.to_numeric(df[col], errors='coerce')
        
        df = df.dropna(subset=['pe', 'Date']).sort_values('Date')
        
        # 修复百分位 (0.x -> x%)
        if 'pe_percentile' in df.columns:
            if df['pe_percentile'].max() <= 1.5: 
                df['pe_percentile'] = df['pe_percentile'] * 100
        else:
            # 如果缺失百分位，给默认值50，防止报错
            df['pe_percentile'] = 50.0 
            
        return df, "Success"
    except Exception as e:
        return None, str(e)

def calculate_metrics(df):
    if df is None or len(df) < 250: return None
    
    df['MA3y'] = df['pe'].rolling(750).mean()
    df['MA5y'] = df['pe'].rolling(1250).mean()
    
    vol = 0.0
    if 'Close' in df.columns:
        df['ret'] = df['Close'].pct_change()
        vol = df['ret'].rolling(20).std().iloc[-1] * np.sqrt(250) * 100
    
    # 均线趋势
    ma60 = 0.0
    if 'Close' in df.columns:
        ma60 = df['Close'].rolling(60).mean().iloc[-1]

    latest = df.iloc[-1]
    
    return {
        "pe": latest['pe'],
        "pct": latest['pe_percentile'], # 统一使用 pe_percentile
        "ma3": latest['MA3y'] if pd.notna(latest['MA3y']) else latest['pe'],
        "ma5": latest['MA5y'] if pd.notna(latest['MA5y']) else latest['pe'],
        "vol": vol,
        "close": latest['Close'] if 'Close' in df.columns else 0,
        "ma60": ma60,
        "date": latest['Date']
    }

def estimate_holding_value(portfolio_item, current_close):
    cost = portfolio_item.get('total_cost', 0.0)
    if cost <= 0: return 0.0
    # 简单估值: 成本
    # 如果有历史记录，可以用 (Current / Last) * Cost 估算市值
    history = portfolio_item.get('history', [])
    if history and current_close > 0:
        last_tx = history[-1]
        last_close = last_tx.get('close', 0.0)
        if last_close > 0:
            return cost * (current_close / last_close)
    return cost

# ==========================================
# 3. 策略引擎 (完全修复版)
# ==========================================

class AdvisorEngine:
    def __init__(self, rf_rate, total_capital, macro_discount, single_limit):
        self.rf = rf_rate
        self.total_capital = total_capital
        self.macro_discount = macro_discount
        self.single_limit = single_limit

    def analyze_index(self, name, metrics, current_val, last_op_date):
        pe = metrics['pe']
        pct = metrics['pct']
        ma5 = metrics['ma5']
        ma3 = metrics['ma3']
        
        deviation = (ma5 - pe) / ma5 * 100 if ma5 > 0 else 0
        premium = (pe - ma5) / ma5 * 100 if ma5 > 0 else 0
        
        signal = "HOLD"
        target_amt = current_val # 默认: 目标=当前 (即不操作)
        reasons = []
        
        # --- A. 买入逻辑 ---
        # 必须满足：估值低于3年&5年均值 且 百分位<20%
        is_buy_zone = (pe < ma3) and (pe < ma5) and (pct < 20)
        
        if is_buy_zone:
            signal = "BUY"
            pos_ratio = 0.0
            
            if 10 <= pct < 20:
                pos_ratio = 0.20; reasons.append("低估(10-20%)")
            elif 2 <= pct < 10:
                pos_ratio = 0.30; reasons.append("极低估(2-10%)")
            elif pct < 10:
                if deviation >= 60: pos_ratio = 1.50; reasons.append("🔥 极低(偏离>60%)")
                elif deviation >= 40: pos_ratio = 1.00; reasons.append("⭐️ 黄金坑(>40%)")
                elif deviation >= 15: pos_ratio = 0.40; reasons.append("👌 显著低估(>15%)")
                else: pos_ratio = 0.30; reasons.append("👀 低百分位")
            
            # 计算买入目标 (基于总配额)
            base_quota = self.total_capital * self.single_limit
            raw_target = base_quota * pos_ratio
            
            # 宏观打折
            if self.macro_discount < 0.8:
                raw_target *= self.macro_discount
                reasons.append(f"📉 大盘高位折算")
            
            # 只有目标 > 当前 才买入
            if raw_target > current_val:
                target_amt = raw_target
            else:
                signal = "HOLD"; reasons.append("✅ 仓位已足")
                
            # 波动率风控
            if metrics['vol'] > 35:
                target_amt = current_val; signal = "WAIT"; reasons.append("🛑 恐慌波动->暂停")

        # --- B. 卖出逻辑 (基于当前持仓打折) ---
        # 触发条件：百分位>60% 且 突破均线 且 溢价>20%
        elif (pct > 60) and (pe > ma3) and (pe > ma5) and (premium > 20):
            signal = "SELL"
            keep_ratio = 1.0 
            if premium > 100: keep_ratio = 0.0; reasons.append("🚨 极度泡沫->清仓")
            elif premium > 80: keep_ratio = 0.20; reasons.append("⚠️ 严重高估->留20%")
            elif premium > 60: keep_ratio = 0.50; reasons.append("📈 显著高估->留50%")
            else: keep_ratio = 0.90; reasons.append("👀 初步高估->微减")
            
            # 关键修复：卖出是基于【当前持仓】打折，而不是总配额
            target_amt = current_val * keep_ratio
            
        # --- C. 趋势止损 (MA60) ---
        elif metrics['close'] < metrics['ma60'] and pct > 40:
             # 如果不是低估区，且破位，且有持仓
             if current_val > 0:
                 signal = "SELL"
                 target_amt = current_val * 0.5 # 减半
                 reasons.append("💔 破MA60止损")

        # --- D. 默认持有 ---
        else:
            signal = "HOLD"
            target_amt = current_val # 锁仓
            if pct > 80: reasons.append("⚠️ 严重高估(观望)")
            elif pct > 50: reasons.append("😐 估值适中")

        # 双重保险：高估绝对不加仓
        if pct > 50 and target_amt > current_val:
            target_amt = current_val
            signal = "HOLD"

        return signal, target_amt, reasons, deviation

# ==========================================
# 4. 页面显示
# ==========================================
with st.sidebar:
    st.header("⚙️ 资金配置")
    total_capital = st.number_input("总账户资金 (¥)", value=500000.0, step=10000.0)
    single_limit = st.slider("单标的上限", 0.1, 0.5, 0.2)
    st.divider()
    if st.button("🔄 刷新"): st.rerun()

portfolio = load_portfolio_state()
results = []
price_history = {}

# 1. 宏观水位
macro_discount = 1.0
broad_pct = 50.0
broad_file = find_csv_file("大盘")
if broad_file:
    df_b, _ = load_and_clean_data(broad_file, "大盘")
    if df_b is not None:
        # 这里统一用 pe_percentile
        broad_pct = df_b['pe_percentile'].iloc[-1] 
        macro_discount = max(0.2, 1.0 - (broad_pct/100))

c1, c2 = st.columns(2)
with c1: st.metric("📉 宏观买入系数", f"{macro_discount:.2f}x", delta=f"大盘PE分位: {broad_pct:.1f}%", delta_color="inverse")
with c2:
    if macro_discount < 0.6: st.warning("⚠️ 大盘高估，限制买入。")
    else: st.success("✅ 大盘适中。")

# 2. 扫描
engine = AdvisorEngine(0, total_capital, macro_discount, single_limit)
progress = st.progress(0)
targets = [x for x in TARGET_INDICES if "大盘" not in x]

for i, name in enumerate(targets):
    progress.progress((i+1)/len(targets))
    
    fpath = find_csv_file(name)
    if not fpath: continue
    
    df, msg = load_and_clean_data(fpath, name)
    if df is None: 
        debug_logs.append(f"{name}: {msg}")
        continue
    
    metrics = calculate_metrics(df)
    if not metrics: continue
    
    price_history[name] = df.set_index('Date')['Close']
    
    # 持仓
    p_data = {}
    for k, v in portfolio.items():
        if name in k: p_data = v; break
    current_val = estimate_holding_value(p_data, metrics['close'])
    
    last_date = None # 暂不卡时间
    signal, target_amt, reasons, dev = engine.analyze_index(name, metrics, current_val, last_date)
    diff = target_amt - current_val
    
    op = "⏸️ 持有"
    if signal == "BUY" and diff > 1000: op = "🟢 建议买入"
    elif signal == "SELL" and diff < -1000: op = "🔴 建议卖出"
    elif signal == "WAIT": op = "⏳ 暂停"
    elif target_amt == 0 and current_val > 100: op = "💥 清仓"
    
    # 高估过滤
    if op == "⏸️ 持有" and current_val < 100 and metrics['pct'] > 60:
        continue
        
    target_pct_show = (target_amt / total_capital) * 100

    results.append({
        "指数": name, "操作": op, "建议仓位": f"{target_pct_show:.1f}%",
        "建议调整": diff, "当前持仓": current_val, "目标金额": target_amt,
        "PE": f"{metrics['pe']:.2f}", "百分位": f"{metrics['pct']:.1f}%", 
        "理由": " ".join(reasons)
    })

progress.empty()

if results:
    df_res = pd.DataFrame(results)
    def style(row):
        if "买入" in row['操作']: return ['background-color: #d1fae5'] * len(row)
        if "卖出" in row['操作']: return ['background-color: #fee2e2'] * len(row)
        return [''] * len(row)
        
    st.subheader("📋 智能决策表")
    st.dataframe(
        df_res.style.apply(style, axis=1).format({
            "建议调整": "{:+,.0f}", "当前持仓": "¥{:,.0f}", "目标金额": "¥{:,.0f}"
        }),
        column_order=["指数", "操作", "建议仓位", "建议调整", "当前持仓", "目标金额", "理由", "PE", "百分位"],
        use_container_width=True, height=600
    )
    
    # 相关性
    with st.expander("🔗 相关性分析"):
        if price_history:
            df_c = pd.DataFrame(price_history).iloc[-250:].pct_change().corr()
            st.dataframe(df_c.style.background_gradient(cmap='Reds'), use_container_width=True)
else:
    st.info("无操作建议。")

with st.expander("🛠️ 调试日志"):
    for l in debug_logs: st.text(l)
