# dashboard.py (V24.10 - 锁定大盘.csv + 宏观风控 + 强力容错)

import streamlit as st
import pandas as pd
import numpy as np
import json
import os
from datetime import datetime, timedelta
import time
import glob
import plotly.express as px
import sys

# ================= 配置区域 =================

# 1. 指数列表
# ⚠️ 修正：已改回 "大盘.csv"，请确保 index_data 文件夹里有这个文件
TARGETS = {
    "大盘.csv": "大盘指数",  # <--- 核心：宏观风控基准
    "沪深300.csv": "沪深300指数",
    "中证500.csv": "中证500指数",
    
    "全指医药.csv": "全指医药",
    "上证50.csv": "上证50",
    "创业板指.csv": "创业板指",
    "养老产业.csv": "养老产业",
    "中证红利.csv": "中证红利",
    "中证环保.csv": "中证环保",
    "中证传媒.csv": "中证传媒",
    "全指金融.csv": "全指金融",
    "证券公司.csv": "证券公司",
    "全指消费.csv": "全指消费",
    "全指信息.csv": "全指信息",
    "中证医疗.csv": "中证医疗",
    "中证白酒.csv": "中证白酒",
}

TARGETS_REVERSE = {v: k for k, v in TARGETS.items()}

# 2. 行业风控配置
SECTOR_CONFIG = {
    "HIGH_CAP_SECTORS": ["全指医药", "全指消费", "中证医疗", "中证白酒", "养老产业"], 
    "MAX_WEIGHT_HIGH": 0.25, # 强周期/热门行业单仓上限 25%
    "MAX_WEIGHT_NORMAL": 0.20 # 普通行业单仓上限 20%
}

DATA_DIR = "index_data"
STATE_FILE = "portfolio_status.json"

# 3. 策略参数
DEFAULT_STRATEGY_PARAMS = {
    "MAX_UNITS": 150,                 
    "AMOUNT_PER_UNIT": 1000.0,        
    "MIN_INTERVAL_DAYS": 30,          
    "VOLATILITY_OVERRIDE_PCT": 0.12,
    "STEP_PERCENT": 0.06
}

# ================= 核心状态函数 =================

def initialize_session_state():
    if 'strategy_params' not in st.session_state:
        st.session_state['strategy_params'] = DEFAULT_STRATEGY_PARAMS

def get_strategy_param(key):
    initialize_session_state()
    return st.session_state['strategy_params'].get(key, DEFAULT_STRATEGY_PARAMS.get(key))

def load_state():
    initial_state = {
        code: {"holdings": 0.0, "total_cost": 0.0, "portions_held": 0.0, "history": []} 
        for code in TARGETS.keys()
    }
    if os.path.exists(STATE_FILE):
        if os.path.getsize(STATE_FILE) == 0: return initial_state
        try:
            with open(STATE_FILE, 'r', encoding='utf-8') as f:
                state = json.load(f)
            for code in TARGETS.keys():
                if code not in state: state[code] = initial_state[code]
                else:
                    if "total_cost" not in state[code]: state[code]["total_cost"] = 0.0 
                    if "holdings" not in state[code]: state[code]["holdings"] = 0.0
                    if "history" not in state[code]: state[code]["history"] = []
                    if "portions_held" not in state[code]: state[code]["portions_held"] = 0.0
                    for h in state[code]["history"]:
                        if "unit" not in h: h['unit'] = 0.0
                        if "portions" in h: h['portions'] = 0
                        if "fund_name" not in h: h['fund_name'] = ""
            return recalculate_holdings_and_cost(state)
        except: return initial_state
    return initial_state

def save_state(state):
    try:
        state_to_save = {}
        for k, data in state.items():
            data_to_save = data.copy()
            if 'history' in data_to_save:
                clean_history = []
                for h in data_to_save['history']:
                    h_copy = h.copy()
                    if hasattr(h_copy['date'], 'strftime'):
                        h_copy['date'] = h_copy['date'].strftime('%Y-%m-%d')
                    clean_history.append(h_copy)
                data_to_save['history'] = clean_history
            state_to_save[k] = data_to_save
            
        with open(STATE_FILE, 'w', encoding='utf-8') as f:
            json.dump(state_to_save, f, ensure_ascii=False, indent=4)
        return True
    except Exception as e:
        st.error(f"保存失败: {e}")
        return False

def calculate_index_cost(history):
    total_units = 0.0
    total_cost = 0.0
    for transaction in history:
        unit = float(transaction.get('unit', 0.0))
        price = float(transaction.get('price', 0.0))
        if transaction.get('type') == '买入':
            total_cost += price * unit
            total_units += unit
        elif transaction.get('type') == '卖出':
            if total_units > 0:
                avg_cost = total_cost / total_units
                total_cost -= avg_cost * unit
                total_units -= unit
                if total_units < 1e-6: total_units = 0.0; total_cost = 0.0
    return max(0.0, total_units), max(0.0, total_cost)

def recalculate_holdings_and_cost(state):
    for code, data in state.items():
        if 'history' in data:
            total_units, total_cost = calculate_index_cost(data['history'])
            state[code]['holdings'] = total_units
            state[code]['total_cost'] = total_cost
            state[code]['portions_held'] = 0 
    return state

# ================= 核心策略逻辑 (宏观+微观) =================

def get_max_allowed_value(index_name, total_capital):
    if index_name in SECTOR_CONFIG["HIGH_CAP_SECTORS"]:
        return total_capital * SECTOR_CONFIG["MAX_WEIGHT_HIGH"] 
    else:
        return total_capital * SECTOR_CONFIG["MAX_WEIGHT_NORMAL"] 

def calculate_target_position_ratio(percentile):
    """
    微观策略：根据估值百分位计算目标仓位比例
    越低估，目标仓位越高
    """
    pct = percentile * 100 
    if pct <= 0: return 1.0    # 极低估，允许满仓
    elif pct <= 2: return 0.70 
    elif pct <= 5: return 0.60 
    elif pct <= 10: return 0.50 
    elif pct <= 15: return 0.30 
    elif pct <= 20: return 0.10 # 建仓位
    else: return 0.0 

def analyze_strategy(index_name, curr_pe, curr_percentile, current_holdings_val, last_op_date_str, total_capital, is_defensive=False):
    max_allowed_val = get_max_allowed_value(index_name, total_capital)
    min_interval = get_strategy_param("MIN_INTERVAL_DAYS")
    
    days_since = 9999
    if last_op_date_str:
        try:
            last_date = datetime.strptime(last_op_date_str, "%Y-%m-%d").date()
            days_since = (datetime.now().date() - last_date).days
        except: pass
    
    is_time_ok = days_since >= min_interval
    time_msg = f"{days_since}天" if days_since < 9999 else "无记录"
    
    logs = []
    signal = "⏸️ 观望"
    action_type = "wait"
    
    # 动态买入阈值
    buy_threshold = 0.05 if is_defensive else 0.20
    
    if is_defensive:
        logs.append(f"🛡️ **防御模式生效中** (总仓位 > 宏观建议)。买入标准已提高至 < 5%。")
    
    target_ratio = calculate_target_position_ratio(curr_percentile)
    target_val = max_allowed_val * target_ratio
    
    # 防御模式下非极低估，停止加仓
    if is_defensive and curr_percentile > 0.05:
        target_val = 0 
    
    # 1. 买入检查
    if current_holdings_val < target_val:
        shortfall = target_val - current_holdings_val
        unit_amt = get_strategy_param("AMOUNT_PER_UNIT")
        
        if curr_percentile <= buy_threshold:
            logs.append(f"PE分位 {curr_percentile*100:.1f}% <= {buy_threshold*100:.0f}%，满足买入。")
            logs.append(f"目标: {target_ratio*100:.0f}% (¥{target_val:,.0f}) | 缺口: ¥{shortfall:,.0f}")
            
            if shortfall > unit_amt / 2: 
                if is_time_ok:
                    signal = f"🟢 建议买入"
                    action_type = "buy"
                    logs.append(f"策略: 满足间隔({min_interval}天)，买入 1 份。")
                else:
                    signal = f"⏳ 等待时间 ({time_msg})"
                    logs.append(f"策略: 冷却期未满。")
            else:
                logs.append("策略: 仓位已达标。")
        else:
            logs.append(f"PE分位 {curr_percentile*100:.1f}% > {buy_threshold*100:.0f}%，不买入。")

    # 2. 卖出检查
    elif curr_percentile > 0.60:
        logs.append(f"PE分位 {curr_percentile*100:.1f}% > 60%，进入止盈区。")
        if is_time_ok:
            signal = f"🔴 建议卖出"
            action_type = "sell"
            logs.append(f"策略: 触发止盈，建议分批卖出。")
        else:
            signal = f"⏳ 等待时间 ({time_msg})"
            logs.append(f"策略: 触发止盈，冷却期未满。")
    else:
        logs.append(f"PE分位 {curr_percentile*100:.1f}%，持有/观望。")

    return signal, logs, action_type

# ================= 数据处理函数 (V24.10 强力清洗+空值保护) =================

def find_pe_by_date(df, target_date_str):
    try:
        target_date = pd.to_datetime(target_date_str)
        df_temp = df.copy()
        df_temp['Date'] = pd.to_datetime(df_temp['Date'], errors='coerce')
        df_temp = df_temp.set_index('Date').sort_index()
        if target_date in df_temp.index:
             row = df_temp.loc[target_date]
             pe = row['pe'].iloc[-1] if isinstance(row, pd.DataFrame) else row['pe']
             close = row['Close'].iloc[-1] if isinstance(row, pd.DataFrame) else row['Close']
             return pe, close
        df_re = df_temp.reindex(df_temp.index.union([target_date]).sort_values()).ffill()
        if target_date in df_re.index:
            row = df_re.loc[target_date]
            if pd.notna(row['pe']): return row['pe'], row['Close']
        return np.nan, np.nan
    except: return np.nan, np.nan

def find_latest_data_file(prefix):
    search_pattern = os.path.join(DATA_DIR, f"{prefix}_*.csv")
    files = glob.glob(search_pattern)
    if files: return max(files, key=os.path.getmtime), os.path.basename(max(files, key=os.path.getmtime)), None
    fixed = os.path.join(DATA_DIR, f"{prefix}.csv")
    if os.path.exists(fixed): return fixed, f"{prefix}.csv", None
    return None, None, None

@st.cache_data(ttl=3600)
def get_metrics_from_csv(file_path):
    # ⚠️ 空值保护
    if not file_path or not os.path.exists(file_path): return None
    try:
        df = pd.read_csv(file_path)
        df = df.rename(columns={'PE-TTM正数等权': 'pe', '日期': 'Date', 'PE-TTM 分位点': 'pe_percentile', '收盘点位': 'Close', '收盘': 'Close'})
        
        # 强力数据清洗
        for col in ['pe', 'pe_percentile', 'Close']:
             if col in df.columns:
                 df[col] = df[col].astype(str).str.replace(r'[^\d.]', '', regex=True)
                 df[col] = pd.to_numeric(df[col], errors='coerce') 
        
        df['Date'] = pd.to_datetime(df['Date'], errors='coerce')
        df = df.dropna(subset=['pe', 'Date']).sort_values('Date').set_index('Date')
        
        if df.empty: return None

        WINDOW_3Y = '1095D'; WINDOW_5Y = '1825D'; WINDOW_10Y = '3650D'
        df['avg_3yr'] = df['pe'].rolling(WINDOW_3Y, min_periods=1).mean()
        df['avg_5yr'] = df['pe'].rolling(WINDOW_5Y, min_periods=1).mean()
        df['avg_10yr'] = df['pe'].rolling(WINDOW_10Y, min_periods=1).mean()
        
        start_dt = df.index[0]
        df.loc[df.index < start_dt + timedelta(days=1095), 'avg_3yr'] = np.nan
        df.loc[df.index < start_dt + timedelta(days=1825), 'avg_5yr'] = np.nan
        df.loc[df.index < start_dt + timedelta(days=3650), 'avg_10yr'] = np.nan
        
        df['deviation'] = (df['pe'] - df['avg_3yr']) / df['avg_3yr'] * 100
        
        curr_pe = df['pe'].iloc[-1]
        curr_pct = df['pe_percentile'].iloc[-1]
        avg_3yr = df['avg_3yr'].iloc[-1]
        avg_5yr = df['avg_5yr'].iloc[-1]
        avg_10yr = df['avg_10yr'].iloc[-1]
        dev_pct = df['deviation'].iloc[-1]
        max_dev = df['deviation'].max()
        min_dev = df['deviation'].min()
        
        return (curr_pe, curr_pct, avg_3yr, avg_5yr, avg_10yr, 
                dev_pct, max_dev, min_dev, df)
    except: return None

def calculate_index_pl_metrics(s, current_close_index):
    holdings = s.get('holdings', 0.0)
    cost = s.get('total_cost', 0.0)
    if holdings <= 0: return 0.0, 0.0, 0.0
    
    avg_cost = cost / holdings
    last_trade = next((t for t in reversed(s['history']) if t.get('price') and t.get('close')), None)
    if last_trade:
        est_price = last_trade['price'] * (current_close_index / last_trade['close'])
        mkt_val = est_price * holdings
        pl_pct = (mkt_val / cost) - 1
        return avg_cost, pl_pct, mkt_val
    return avg_cost, 0.0, cost

# ================= 页面主程序 =================

st.set_page_config(page_title="智能资产配置", layout="wide", page_icon="📈")

st.markdown("""
<style>
div[data-testid="stMetricValue"] > div { font-size: 20px !important; font-weight: bold; }
div[data-testid="stMetricLabel"] label { font-size: 13px !important; }
div[data-testid="stVerticalBlock"] > div[data-testid="stHorizontalBlock"] > div[data-testid="stVerticalBlock"] { min-height: 125px; }
</style>
""", unsafe_allow_html=True)

initialize_session_state()

# --- 侧边栏 ---
st.sidebar.header("🕹️ 策略配置 (V24.10)")
with st.sidebar.expander("⚙️ 资产参数", expanded=True):
    AMOUNT_PER_UNIT = st.number_input("每份金额 (¥):", min_value=100.0, value=get_strategy_param("AMOUNT_PER_UNIT"), step=100.0, key='p_amt')
    MAX_UNITS = st.number_input("总资金份数:", min_value=10, value=get_strategy_param("MAX_UNITS"), step=10, key='p_max')
    MIN_INTERVAL = st.number_input("风控间隔 (天):", min_value=1, value=get_strategy_param("MIN_INTERVAL_DAYS"), key='p_int')
    
    TOTAL_CAPITAL = AMOUNT_PER_UNIT * MAX_UNITS
    st.caption(f"💰 总资金池: ¥{TOTAL_CAPITAL:,.0f}")
    
    if st.button("保存设置"):
        st.session_state['strategy_params'].update({
            "AMOUNT_PER_UNIT": AMOUNT_PER_UNIT,
            "MAX_UNITS": MAX_UNITS,
            "MIN_INTERVAL_DAYS": MIN_INTERVAL
        })
        st.success("参数已更新")
        st.rerun()

AMOUNT_PER_UNIT = get_strategy_param("AMOUNT_PER_UNIT")
MAX_UNITS = get_strategy_param("MAX_UNITS")
MIN_INTERVAL = get_strategy_param("MIN_INTERVAL_DAYS")
TOTAL_CAPITAL = AMOUNT_PER_UNIT * MAX_UNITS

# ================= 宏观水位计算 =================
state = load_state()

# 1. 资金使用率
total_invested_cost = sum(s['total_cost'] for s in state.values())
current_usage_ratio = total_invested_cost / TOTAL_CAPITAL if TOTAL_CAPITAL > 0 else 0

# 2. 获取大盘水位 (精确查找)
broad_market_percentile = np.nan
broad_index_key = next((k for k, v in TARGETS.items() if v == "大盘指数"), None)

if broad_index_key:
    broad_prefix = broad_index_key.split('.')[0]
    broad_file_path, _, _ = find_latest_data_file(broad_prefix)
    
    # ⚠️ V24.10 修复：确保路径存在才调用
    if broad_file_path:
        broad_metrics = get_metrics_from_csv(broad_file_path)
        if broad_metrics:
            broad_market_percentile = broad_metrics[1] # curr_pct

# 3. 判定防御模式
is_defensive_mode = False
macro_limit_ratio = 1.0

if not np.isnan(broad_market_percentile):
    # 核心公式：宏观上限 = 1 - 大盘PE分位
    macro_limit_ratio = 1.0 - broad_market_percentile
    # 极低估保护：大盘 < 10% 时不设限
    if broad_market_percentile < 0.10: macro_limit_ratio = 1.0
    
    if current_usage_ratio > macro_limit_ratio:
        is_defensive_mode = True

# --- 头部看板 ---
with st.container(border=True):
    st.markdown("## 📊 智能资产配置看板 (大盘水位控制版)")
    
    c_h1, c_h2 = st.columns([2, 1])
    with c_h1:
        st.markdown(f"**资产概览**: 总资金 **¥{TOTAL_CAPITAL:,.0f}** | 已用本金 **¥{total_invested_cost:,.0f} ({current_usage_ratio*100:.1f}%)**")
    
    with c_h2:
        if not np.isnan(broad_market_percentile):
            st.metric("大盘水位 (PE百分位)", f"{broad_market_percentile*100:.1f}%", 
                      delta=f"建议总仓位上限 {(macro_limit_ratio)*100:.1f}%", delta_color="inverse")
            st.caption(f"基于 '{broad_index_key}'")
        else:
            st.warning("⚠️ 未能读取 '大盘.csv'，宏观风控失效")

    if is_defensive_mode:
        st.error(f"🛡️ **防御模式已激活**：总仓位({current_usage_ratio*100:.1f}%) > 建议上限({macro_limit_ratio*100:.1f}%)。买入标准已大幅提高 (仅 <5% 可买)。")
    else:
        st.success(f"✅ **正常模式**：当前仓位安全。按标准阶梯策略执行。")

table_data = []
decision_logs = {}
pie_data = []
total_mkt_value = 0.0
valid_signals = {"buy": 0, "sell": 0}
full_data_frames = {}

# --- 数据分析循环 ---
progress = st.progress(0, text="加载市场数据...")
for i, (fname, name) in enumerate(TARGETS.items()):
    progress.progress((i+1)/len(TARGETS), text=f"分析 {name}...")
    
    fpath, _, _ = find_latest_data_file(fname.split('.')[0])
    
    metrics = None
    if fpath:
        metrics = get_metrics_from_csv(fpath)
        
    s = state.get(fname, {})
    holdings = s.get('holdings', 0.0)
    last_op = s['history'][-1] if s['history'] else None
    last_date = last_op['date'] if last_op else ""
    last_pe_val = last_op['pe'] if last_op and 'pe' in last_op else np.nan
    
    days_since_op = (datetime.now().date() - datetime.strptime(last_date, '%Y-%m-%d').date()).days if last_date else "—"
    
    if metrics:
        curr_pe, curr_pct, avg3, avg5, avg10, dev_pct, max_dev, min_dev, df_full = metrics
        full_data_frames[fname] = df_full 
        curr_close = df_full['Close'].iloc[-1]
        
        avg_cost, pl_pct, mkt_val = calculate_index_pl_metrics(s, curr_close)
        
        if holdings > 0:
            pie_data.append({"name": name, "value": mkt_val})
            total_mkt_value += mkt_val
            
        signal_txt, logs, action = analyze_strategy(name, curr_pe, curr_pct, mkt_val, last_date, TOTAL_CAPITAL, is_defensive_mode)
        
        if action != "wait": valid_signals[action] += 1
        decision_logs[fname] = logs
        
        table_data.append({
            "指数名称": name,
            "建议信号": signal_txt,
            "PE百分位": f"{curr_pct*100:.1f}%",
            "当前PE": f"{curr_pe:.2f}",
            "偏离度(3年)": f"{dev_pct:.1f}%" if not np.isnan(dev_pct) else "—",
            "最大偏离": f"{max_dev:.1f}%" if not np.isnan(max_dev) else "—",
            "最小偏离": f"{min_dev:.1f}%" if not np.isnan(min_dev) else "—",
            "持仓市值": f"¥{mkt_val:,.0f}",
            "平均成本(ETF)": f"{avg_cost:.4f}" if holdings > 0 else "—",
            "浮动盈亏": f"{pl_pct*100:.2f}%" if holdings > 0 else "—",
            "上次操作距今": f"{days_since_op}天" if last_date else "—",
            "上次操作PE": f"{last_pe_val:.2f}" if not np.isnan(last_pe_val) else "—",
            "持仓份额": f"{holdings:.2f}"
        })
    else:
        table_data.append({"指数名称": name, "建议信号": "⚠️ 数据缺失", "PE百分位": "—", "当前PE": "—", 
            "偏离度(3年)": "—", "最大偏离": "—", "最小偏离": "—", "持仓市值": "—", 
            "平均成本(ETF)": "—", "浮动盈亏": "—", "上次操作距今": "—", "上次操作PE": "—", "持仓份额": "—"})
progress.empty()

# --- 侧边栏饼图 ---
with st.sidebar:
    st.markdown("---")
    remaining_cash = max(0, TOTAL_CAPITAL - total_invested_cost)
    
    if pie_data:
        pie_df = pd.DataFrame(pie_data)
    else:
        pie_df = pd.DataFrame(columns=["name", "value"])
    
    if remaining_cash > 1:
        new_row = pd.DataFrame([{"name": "剩余本金/可用额度", "value": remaining_cash}])
        pie_df = pd.concat([pie_df, new_row], ignore_index=True)
    
    if not pie_df.empty and pie_df['value'].sum() > 0:
        fig = px.pie(pie_df, values='value', names='name', title="资产配置预览 (市值)", hole=0.4)
        fig.update_layout(margin=dict(t=30, b=0, l=0, r=0), height=300, showlegend=False)
        st.plotly_chart(fig, use_container_width=True)
    else:
        st.info("暂无持仓数据。")

# --- 核心指标 ---
c1, c2, c3, c4 = st.columns(4)
with c1.container(border=True):
    st.markdown("### 💰 资金状态")
    usage_pct = (total_invested_cost / TOTAL_CAPITAL * 100) if TOTAL_CAPITAL > 0 else 0
    st.metric("本金使用率", f"{usage_pct:.1f}%")
    st.caption(f"已用本金: ¥{total_invested_cost/10000:.1f}万")
    st.caption(f"持仓市值: ¥{total_mkt_value/10000:.1f}万")

with c2.container(border=True):
    st.markdown("### 🎯 信号监控")
    st.metric("操作建议", f"买入{valid_signals['buy']} / 卖出{valid_signals['sell']}")
    if is_defensive_mode:
        st.caption(":red[🛡️ 防御模式生效中]")
    else:
        st.caption(":green[✅ 正常定投模式]")
    st.caption(f"风控间隔: {MIN_INTERVAL}天")

with c3.container(border=True):
    st.markdown("### 📊 市场热度")
    avg_pct = np.mean([float(x['PE百分位'].strip('%')) for x in table_data if x['PE百分位'] != '—']) if table_data else 0
    st.metric("平均PE分位", f"{avg_pct:.1f}%")
    if avg_pct < 20: st.caption(":green[整体低估机会]")
    elif avg_pct > 80: st.caption(":red[整体高估风险]")
    else: st.caption("估值适中")
    st.caption(" ")

with c4.container(border=True):
    st.markdown("### 🛡️ 风控限制")
    st.metric("单份金额", f"¥{AMOUNT_PER_UNIT:,.0f}")
    st.caption(f"医药/消费: 25% (¥{TOTAL_CAPITAL*0.25:,.0f})")
    st.caption(f"其他行业: 20% (¥{TOTAL_CAPITAL*0.2:,.0f})")

st.markdown("---")

# --- 主表格与日志 ---
def color_signal(val):
    if "买入" in val: return 'background-color: #d4edda; color: #155724; font-weight: bold'
    if "卖出" in val: return 'background-color: #f8d7da; color: #721c24; font-weight: bold'
    if "等待" in val: return 'color: #856404; font-weight: bold'
    return ''

display_cols = [
    "指数名称", "建议信号", "PE百分位", "当前PE", "偏离度(3年)", 
    "最大偏离", "最小偏离", "上次操作距今", "持仓市值", "平均成本(ETF)", "浮动盈亏", "持仓份额"
]
df_final = pd.DataFrame(table_data)
for c in display_cols:
    if c not in df_final.columns: df_final[c] = "—"

st.dataframe(df_final[display_cols].style.applymap(color_signal, subset=['建议信号']), use_container_width=True, height=500)

with st.expander("📝 查看策略详细分析日志"):
    sel_log = st.selectbox("选择指数:", list(TARGETS.values()))
    log_key = [k for k,v in TARGETS.items() if v == sel_log][0]
    if log_key in decision_logs:
        for l in decision_logs[log_key]: st.text(f"• {l}")

# ================= 交易管理区域 =================
st.markdown("---")
st.header("🛒 交易管理中心")

tab_add, tab_manage, tab_import = st.tabs(["📝 登记新交易", "⚙️ 修改/删除记录", "📤 批量导入"])

# --- Tab 1: 登记 ---
with tab_add:
    c1, c2, c3, c4 = st.columns(4)
    with c1: 
        r_name = st.selectbox("指数", list(TARGETS.values()), key='r_n')
        r_file = [k for k,v in TARGETS.items() if v == r_name][0]
    with c2: r_type = st.selectbox("方向", ["买入", "卖出"], key='r_t')
    with c3: r_price = st.number_input("净值", value=1.000, format="%.4f", key='r_p')
    with c4: r_share = st.number_input("份额", value=AMOUNT_PER_UNIT/r_price, format="%.2f", key='r_s')
    r_fund = st.text_input("基金名称/代码", key='r_f')
    r_date = st.date_input("日期", value=datetime.now(), key='r_d')
    
    if st.button("提交交易", type="primary"):
        s = state[r_file]
        df_f = full_data_frames.get(r_file)
        pe_v, cl_v = find_pe_by_date(df_f, r_date.strftime("%Y-%m-%d")) if df_f is not None else (None, None)
        
        if r_type == '卖出' and s['holdings'] < r_share:
            st.error(f"份额不足! 当前: {s['holdings']:.2f}")
        else:
            new_record = {
                "date": r_date.strftime("%Y-%m-%d"),
                "type": r_type,
                "price": r_price,
                "unit": r_share,
                "pe": pe_v,
                "close": cl_v,
                "fund_name": r_fund
            }
            s['history'].append(new_record)
            save_state(recalculate_holdings_and_cost(state))
            st.success("✅ 交易已记录")
            time.sleep(1); st.rerun()

# --- Tab 2: 管理 ---
with tab_manage:
    m_name = st.selectbox("选择指数管理记录:", list(TARGETS.values()), key='m_n')
    m_file = [k for k,v in TARGETS.items() if v == m_name][0]
    m_s = state[m_file]
    
    if m_s['history']:
        hist_df = pd.DataFrame(m_s['history'])
        hist_df['index'] = hist_df.index
        cols_to_show = ['index', 'date', 'type', 'price', 'unit', 'fund_name']
        st.dataframe(hist_df[[c for c in cols_to_show if c in hist_df.columns]], hide_index=True)
        
        c_del, c_mod = st.columns(2)
        with c_del:
            del_idx = st.number_input("删除行索引:", min_value=0, max_value=len(m_s['history'])-1, step=1, key='d_i')
            if st.button("🗑️ 删除记录"):
                del m_s['history'][del_idx]
                save_state(recalculate_holdings_and_cost(state))
                st.success("已删除!"); time.sleep(1); st.rerun()
    else:
        st.info("暂无记录")

# --- Tab 3: 导入 ---
with tab_import:
    st.info("支持列名: 日期, 操作类型, 净值, 份额, 基金代码, 所属指数")
    up_file = st.file_uploader("上传 Excel/CSV", type=["csv", "xlsx"])
    if up_file:
        try:
            df_imp = pd.read_excel(up_file) if up_file.name.endswith('xlsx') else pd.read_csv(up_file)
            st.dataframe(df_imp.head())
            if st.button(f"确认导入 {len(df_imp)} 条"):
                count = 0
                for _, row in df_imp.iterrows():
                    t_idx = TARGETS_REVERSE.get(row['所属指数'].strip())
                    if t_idx:
                        df_f = full_data_frames.get(t_idx)
                        d_str = pd.to_datetime(row['日期']).strftime("%Y-%m-%d")
                        pe_v, cl_v = find_pe_by_date(df_f, d_str) if df_f is not None else (None, None)
                        
                        state[t_idx]['history'].append({
                            "date": d_str, "type": row['操作类型'], 
                            "price": row['净值'], "unit": row['份额'], 
                            "fund_name": row['基金代码'], "pe": pe_v, "close": cl_v
                        })
                        count += 1
                save_state(recalculate_holdings_and_cost(state))
                st.success(f"成功导入 {count} 条!"); time.sleep(2); st.rerun()
        except Exception as e: st.error(f"导入失败: {e}")
