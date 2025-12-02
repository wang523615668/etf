# dashboard.py (V25.17 - 修复图表标题遮挡 + 强力清洗 + 核心总览表)

import streamlit as st
import pandas as pd
import numpy as np
import json
import os
from datetime import datetime, timedelta
import time
import glob
import plotly.express as px
import plotly.graph_objects as go

# ================= 1. 系统配置 =================

st.set_page_config(page_title="智能资产配置 Pro", layout="wide", page_icon="📈")

DATA_DIR = "index_data"
STATE_FILE = "portfolio_status.json"

# 指数列表
TARGETS = {
    "大盘": "大盘指数", 
    "沪深300": "沪深300",
    "中证500": "中证500",
    "创业板": "创业板指",
    "上证50": "上证50",
    "白酒": "中证白酒",
    "医疗": "中证医疗",
    "医药": "全指医药",
    "消费": "全指消费",
    "养老": "养老产业",
    "红利": "中证红利",
    "金融": "全指金融",
    "证券": "证券公司",
    "传媒": "中证传媒",
    "环保": "中证环保",
    "信息": "全指信息",
}

DEFAULT_STRATEGY_PARAMS = {
    "MAX_UNITS": 150, "AMOUNT_PER_UNIT": 1000.0, "MIN_INTERVAL_DAYS": 30
}

# ================= 2. 核心数据引擎 =================

def initialize_session_state():
    if 'strategy_params' not in st.session_state:
        st.session_state['strategy_params'] = DEFAULT_STRATEGY_PARAMS

def get_strategy_param(key):
    initialize_session_state()
    return st.session_state['strategy_params'].get(key, DEFAULT_STRATEGY_PARAMS.get(key))

def load_state():
    initial_state = {v: {"holdings": 0.0, "total_cost": 0.0, "history": []} for v in TARGETS.values()}
    if os.path.exists(STATE_FILE):
        try:
            with open(STATE_FILE, 'r', encoding='utf-8') as f: 
                state = json.load(f)
            for k in initial_state.keys():
                if k not in state: state[k] = initial_state[k]
            return state
        except: return initial_state
    return initial_state

def save_state(state):
    try:
        with open(STATE_FILE, 'w', encoding='utf-8') as f:
            json.dump(state, f, ensure_ascii=False, indent=4)
        return True
    except Exception as e: return False

def recalculate_holdings(state):
    for code, data in state.items():
        if 'history' in data:
            units, cost = 0.0, 0.0
            for t in data['history']:
                u, p = float(t.get('unit',0)), float(t.get('price',0))
                if t['type'] == '买入': cost += p*u; units += u
                elif t['type'] == '卖出':
                    if units > 0:
                        avg = cost/units; cost -= avg*u; units -= u
                        if units < 1e-6: units=0; cost=0
            state[code]['holdings'] = max(0, units)
            state[code]['total_cost'] = max(0, cost)
    return state

def find_csv_for_target(target_keyword):
    if not os.path.exists(DATA_DIR): return None
    candidates = glob.glob(os.path.join(DATA_DIR, f"*{target_keyword}*.csv"))
    if not candidates: return None
    return max(candidates, key=os.path.getmtime)

@st.cache_data(ttl=600)
def get_metrics_from_csv(file_path):
    if not file_path: return None
    try:
        # 1. 尝试读取
        try:
            df = pd.read_csv(file_path, encoding='utf-8')
        except UnicodeDecodeError:
            df = pd.read_csv(file_path, encoding='gbk')
        
        # 2. 列名标准化
        rename_map = {}
        for col in df.columns:
            c_lower = str(col).lower()
            if '日期' in col or 'date' in c_lower: rename_map[col] = 'Date'
            elif '收盘' in col or 'close' in c_lower: rename_map[col] = 'Close'
            elif '分位' in col: rename_map[col] = 'pe_percentile'
            elif 'pe' in c_lower or '市盈率' in col: rename_map[col] = 'pe'
        
        df = df.rename(columns=rename_map)
        df = df.loc[:, ~df.columns.duplicated()] # 去重
        
        # 3. 强力清洗
        cols_to_clean = ['pe', 'Close', 'pe_percentile']
        for c in cols_to_clean:
            if c in df.columns:
                if df[c].dtype == object:
                    df[c] = df[c].astype(str).str.replace('=', '').str.replace('"', '').str.replace(',', '')
                df[c] = pd.to_numeric(df[c], errors='coerce')
        
        # 4. 基础处理
        df['Date'] = pd.to_datetime(df['Date'], errors='coerce')
        df = df.dropna(subset=['Date', 'pe']).sort_values('Date').set_index('Date')
        if df.empty: return None
        
        # 5. 计算指标
        curr_pe = df['pe'].iloc[-1]
        curr_close = df['Close'].iloc[-1] if 'Close' in df.columns else 0.0
        
        if 'pe_percentile' not in df.columns:
            if len(df) > 10:
                df['pe_percentile'] = df['pe'].rank(pct=True)
            else:
                df['pe_percentile'] = 0.5 
        
        curr_pct = df['pe_percentile'].iloc[-1]
        
        df['avg_3yr'] = df['pe'].rolling(window=750, min_periods=1).mean()
        df['avg_5yr'] = df['pe'].rolling(window=1250, min_periods=1).mean()
        
        avg_3yr = df['avg_3yr'].iloc[-1] if not pd.isna(df['avg_3yr'].iloc[-1]) else curr_pe
        avg_5yr = df['avg_5yr'].iloc[-1] if not pd.isna(df['avg_5yr'].iloc[-1]) else avg_3yr
        long_term_avg = avg_5yr if len(df) >= 750 else avg_3yr
        
        return curr_pe, curr_pct, avg_3yr, avg_5yr, long_term_avg, curr_close, df
        
    except Exception as e:
        return None

# === 修复核心：布局调整 ===
def plot_pe_bands(df, index_name):
    if 'Close' not in df.columns or 'pe' not in df.columns: return None
    
    df['Close'] = pd.to_numeric(df['Close'], errors='coerce')
    df['pe'] = pd.to_numeric(df['pe'], errors='coerce')
    df['Earnings'] = df['Close'] / df['pe']
    
    recent_df = df.iloc[-1250:] if len(df) > 1250 else df
    pe_20 = recent_df['pe'].quantile(0.20)
    pe_50 = recent_df['pe'].quantile(0.50)
    pe_80 = recent_df['pe'].quantile(0.80)
    
    smooth_earnings = df['Earnings'].rolling(window=20, min_periods=1).mean()
    
    df['Band_High'] = smooth_earnings * pe_80
    df['Band_Mid'] = smooth_earnings * pe_50
    df['Band_Low'] = smooth_earnings * pe_20
    
    plot_df = df.iloc[-750:] if len(df) > 750 else df
    
    fig = go.Figure()
    fig.add_trace(go.Scatter(x=plot_df.index, y=plot_df['Close'], name='当前价格', line=dict(color='black', width=2)))
    fig.add_trace(go.Scatter(x=plot_df.index, y=plot_df['Band_High'], name=f'高估({pe_80:.1f})', line=dict(color='#ff4d4d', width=1, dash='dot')))
    fig.add_trace(go.Scatter(x=plot_df.index, y=plot_df['Band_Mid'], name=f'中枢({pe_50:.1f})', line=dict(color='#ffa500', width=1, dash='dot')))
    fig.add_trace(go.Scatter(x=plot_df.index, y=plot_df['Band_Low'], name=f'低估({pe_20:.1f})', line=dict(color='#2ecc71', width=1, dash='dot')))
    
    # ⚠️ 修复点：调整 layout
    fig.update_layout(
        title=dict(
            text=f"📈 {index_name} - 估值通道图",
            x=0.01, # 标题靠左
            y=0.95  # 标题置顶
        ),
        height=400,
        # 增加顶部边距 (t=80)，防止遮挡
        margin=dict(l=20, r=20, t=80, b=20), 
        legend=dict(
            orientation="h", 
            y=1.15, # 图例上移
            x=0
        ),
        hovermode="x unified"
    )
    return fig

# ================= 3. 主界面逻辑 =================

initialize_session_state()
state = load_state()

# --- 侧边栏 ---
with st.sidebar:
    st.header("⚙️ 策略参数")
    AMT = st.number_input("定投金额", value=get_strategy_param("AMOUNT_PER_UNIT"))
    MAX_U = st.number_input("总份数", value=get_strategy_param("MAX_UNITS"))
    if st.button("保存参数"):
        st.session_state['strategy_params'].update({"AMOUNT_PER_UNIT": AMT, "MAX_UNITS": MAX_U})
        st.success("已保存")

# --- 宏观水位 ---
col_k1, col_k2 = st.columns([2, 1])
macro_pct = np.nan
macro_file = find_csv_for_target("大盘")
if macro_file:
    m = get_metrics_from_csv(macro_file)
    if m: macro_pct = m[1]

with col_k2.container(border=True):
    if not np.isnan(macro_pct):
        st.metric("大盘水位", f"{macro_pct*100:.1f}%", delta="基于全A/上证", delta_color="inverse")
    else: st.warning("缺大盘数据")

st.markdown("---")

# --- 核心功能：数据处理与表格生成 ---
table_rows = []
analysis_list = []

for kw, name in TARGETS.items():
    fpath = find_csv_for_target(kw)
    res = get_metrics_from_csv(fpath)
    
    s = state.get(name, {})
    holdings = s.get('holdings', 0.0)
    cost = s.get('total_cost', 0.0)
    
    if res:
        curr_pe, curr_pct, avg3, avg5, long_avg, curr_close, df_hist = res
        
        # 策略逻辑
        signal = "⏸️ 观望"
        status = "normal"
        
        is_low_pct = curr_pct < 0.20
        is_below_avg = curr_pe < long_avg
        
        if is_low_pct and is_below_avg:
            signal = "🟢 强力买入"
            status = "buy_strong"
        elif is_low_pct and not is_below_avg:
            signal = "🟡 观望(高于均线)"
            status = "watch_avg"
        elif curr_pct < 0.40 and is_below_avg:
            signal = "🔵 定投区"
            status = "buy_normal"
        elif curr_pct > 0.80:
            signal = "🔴 止盈区"
            status = "sell"
        
        market_value = holdings * curr_close if curr_close > 0 else cost
        profit = market_value - cost
        profit_pct = (profit / cost) if cost > 0 else 0.0
        
        table_rows.append({
            "指数名称": name,
            "建议信号": signal,
            "PE百分位": f"{curr_pct*100:.1f}%",
            "当前PE": f"{curr_pe:.2f}",
            "5年均线": f"{long_avg:.2f}",
            "偏离度": f"{(curr_pe - long_avg)/long_avg*100:+.1f}%",
            "持仓市值": f"¥{market_value:,.0f}",
            "持仓收益": f"{profit_pct*100:+.2f}%" if cost > 0 else "—",
            "最新净值": f"{curr_close:.4f}"
        })
        
        analysis_list.append({
            "name": name, "pct": curr_pct, "pe": curr_pe, "avg": long_avg,
            "signal": signal, "status": status, "df": df_hist
        })
    else:
        table_rows.append({
            "指数名称": name, "建议信号": "❌ 文件错误", "PE百分位": "—", "当前PE": "—",
            "5年均线": "—", "偏离度": "—", "持仓市值": "—", "持仓收益": "—", "最新净值": "—"
        })
        analysis_list.append({"name": name, "pct": 999, "signal": "❌ 文件错误", "status": "err"})

# === 1. 显示核心资产总览表 ===
st.subheader("📋 核心资产总览")

def color_signal(val):
    if "强力买入" in str(val): return 'background-color: #d4edda; color: #155724; font-weight: bold'
    if "定投区" in str(val): return 'color: #004085; font-weight: bold'
    if "止盈区" in str(val): return 'background-color: #f8d7da; color: #721c24; font-weight: bold'
    if "观望" in str(val): return 'color: #856404'
    return ''

if table_rows:
    df_table = pd.DataFrame(table_rows)
    st.dataframe(
        df_table.style.applymap(color_signal, subset=['建议信号']),
        use_container_width=True,
        height=500 
    )

st.markdown("---")

# === 2. 详情与图表 ===
st.subheader("🔍 深度分析与通道图")

analysis_list.sort(key=lambda x: (
    0 if x.get('status') == 'buy_strong' else 
    1 if x.get('status') == 'buy_normal' else 
    2 if x.get('status') == 'watch_avg' else 3
))

c_list, c_chart = st.columns([1, 3])

with c_list:
    st.caption("选择查看详情 👇")
    selected_name = st.radio("资产列表", [x['name'] for x in analysis_list], label_visibility="collapsed")
    item = next(x for x in analysis_list if x['name'] == selected_name)

with c_chart:
    if item.get('df') is not None:
        k1, k2, k3 = st.columns(3)
        k1.metric("当前PE", f"{item['pe']:.2f}")
        k2.metric("5年均线", f"{item['avg']:.2f}", delta=f"{item['pe'] - item['avg']:.2f}", delta_color="inverse")
        k3.metric("PE分位", f"{item['pct']*100:.1f}%")
        
        st.info(f"**操作建议**: {item['signal']}")
        
        fig = plot_pe_bands(item['df'], item['name'])
        st.plotly_chart(fig, use_container_width=True)
        
    else:
        st.error("❌ 无法读取该指数数据")

# --- 记账模块 ---
st.divider()
with st.expander("📝 记账"):
    c1,c2,c3,c4 = st.columns(4)
    t_n = c1.selectbox("指数", list(TARGETS.values()))
    t_d = c2.selectbox("方向", ["买入", "卖出"])
    t_p = c3.number_input("净值", 1.0)
    t_u = c4.number_input("份额", 100.0)
    if st.button("保存"):
        d_str = datetime.now().strftime("%Y-%m-%d")
        curr_pe = 0
        f_csv = find_csv_for_target(next(k for k,v in TARGETS.items() if v==t_n))
        if f_csv:
             m = get_metrics_from_csv(f_csv)
             if m: curr_pe = m[0]
             
        state[t_n]['history'].append({"date": d_str, "type": t_d, "price": t_p, "unit": t_u, "pe": curr_pe})
        save_state(recalculate_holdings(state))
        st.success("已保存")
        time.sleep(0.5); st.rerun()
