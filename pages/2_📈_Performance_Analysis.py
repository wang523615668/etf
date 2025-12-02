# pages/2_📈_Performance_Analysis.py (V24.11 - 修复 KeyError: Date)

import streamlit as st
import pandas as pd
import numpy as np
import plotly.express as px
import os
import sys
from datetime import datetime, timedelta

# ----------------------------------------------------
current_dir = os.path.dirname(os.path.abspath(__file__))
parent_dir = os.path.abspath(os.path.join(current_dir, '..'))
if parent_dir not in sys.path:
    sys.path.insert(0, parent_dir)
# ----------------------------------------------------

try:
    from dashboard import TARGETS, load_state, get_metrics_from_csv, find_latest_data_file, calculate_index_pl_metrics
except ImportError:
    st.error("导入配置失败。请确保 dashboard.py 正常。")
    st.stop()

st.set_page_config(page_title="性能分析", layout="wide", page_icon="📈")

def calculate_cagr(start_price, end_price, days):
    if days == 0 or start_price == 0: return np.nan
    return (end_price / start_price)**(365.25 / days) - 1

def calculate_max_drawdown(series):
    if series.empty: return 0.0
    return ((series / series.cummax()) - 1).min()

@st.cache_data(ttl=3600)
def load_all_index_data():
    st.info("🔄 加载数据中...")
    data_dict = {}
    
    for fname, name in TARGETS.items():
        prefix = fname.split('.')[0]
        fpath, _, _ = find_latest_data_file(prefix)
        
        if fpath:
            metrics = get_metrics_from_csv(fpath)
            if metrics:
                # V24.11 修复：重置索引
                df = metrics[-1]
                df = df.reset_index() # <--- 关键修复：找回 Date 列
                
                df = df.rename(columns={'Date': 'date', 'Close': 'close'})
                df['date'] = pd.to_datetime(df['date'])
                df = df.set_index('date').sort_index()
                data_dict[name] = df['close']
                
    if not data_dict: return None

    # 合并数据
    combined = pd.DataFrame(data_dict).ffill()
    st.success(f"✅ 加载 {len(data_dict)} 个指数")
    return combined

def calculate_relative_return(df, start_date):
    sub = df[df.index >= pd.to_datetime(start_date)].copy()
    if sub.empty: return pd.DataFrame()
    return sub.div(sub.iloc[0])

def app():
    st.header("📈 市场表现与持仓透视")
    st.markdown("---")

    combined_df = load_all_index_data()
    if combined_df is None or combined_df.empty:
        st.warning("无有效数据。")
        return

    state = load_state()
    
    # --- 交互 ---
    c1, c2, c3 = st.columns([2, 1, 1])
    all_names = list(combined_df.columns)
    
    # 默认选中有持仓的
    holdings = [TARGETS[k] for k, v in state.items() if v.get('holdings', 0) > 0]
    defaults = [n for n in holdings if n in all_names]
    if not defaults: defaults = all_names[:5]
    
    with c1: selected = st.multiselect("选择指数:", all_names, default=defaults)
    if not selected: return

    min_d, max_d = combined_df.index.min().date(), combined_df.index.max().date()
    
    with c3:
        period = st.selectbox("周期:", ["近1年", "近3年", "近5年", "YTD", "自定义"])
        days_map = {"近1年": 365, "近3年": 1095, "近5年": 1825}
    
    with c2:
        if period == "自定义":
            s_date = st.date_input("开始:", value=max_d-timedelta(days=365), min_value=min_d, max_value=max_d)
        elif period == "YTD":
            s_date = datetime(max_d.year, 1, 1).date()
        else:
            s_date = max_d - timedelta(days=days_map.get(period, 365))
        if s_date < min_d: s_date = min_d

    # --- 计算 ---
    df_rel = calculate_relative_return(combined_df[selected], s_date)
    if df_rel.empty:
        st.error("区间无数据")
        return

    # --- 图表 ---
    st.markdown("---")
    st.subheader("📈 收益走势 (归一化)")
    fig = px.line(df_rel, x=df_rel.index, y=df_rel.columns)
    st.plotly_chart(fig, use_container_width=True)

    # --- 汇总表 ---
    st.subheader("💰 详细指标")
    summary = []
    
    # 反查 Key
    NAME_TO_KEY = {v: k for k, v in TARGETS.items()}
    
    for name in selected:
        ser = df_rel[name]
        start_v, end_v = ser.iloc[0], ser.iloc[-1]
        
        # 市场指标
        ret = (end_v - 1) * 100
        mdd = calculate_max_drawdown(ser) * 100
        days = (ser.index[-1] - ser.index[0]).days
        cagr = calculate_cagr(start_v, end_v, days) * 100
        
        # 持仓指标
        key = NAME_TO_KEY.get(name)
        s_data = state.get(key, {})
        curr_price = combined_df[name].iloc[-1]
        avg_c, pl_p, _ = calculate_index_pl_metrics(s_data, curr_price)
        
        summary.append({
            "指数": name,
            "涨跌幅(%)": ret,
            "最大回撤(%)": mdd,
            "CAGR(%)": cagr,
            "持仓(份)": s_data.get('holdings', 0),
            "持仓盈亏(%)": pl_p * 100 if s_data.get('holdings', 0) > 0 else np.nan
        })
        
    df_sum = pd.DataFrame(summary).set_index("指数")
    
    # V24.11 适配旧版 Pandas applymap
    st.dataframe(
        df_sum.style.format("{:.2f}")
        .applymap(lambda x: 'color: green' if x > 0 else 'color: red', subset=["涨跌幅(%)", "CAGR(%)", "持仓盈亏(%)"]),
        use_container_width=True
    )

if __name__ == "__main__":
    app()
