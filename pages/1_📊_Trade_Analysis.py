# pages/1_📊_Trade_Analysis.py (V24.12 - 修复 KeyError 并恢复 10年均线)

import streamlit as st
import pandas as pd
import numpy as np
import plotly.graph_objects as go
from plotly.subplots import make_subplots
from datetime import datetime
import os
import sys

# ----------------------------------------------------
# 路径设置：确保能找到父目录的 dashboard.py
current_dir = os.path.dirname(os.path.abspath(__file__))
parent_dir = os.path.abspath(os.path.join(current_dir, '..'))
if parent_dir not in sys.path:
    sys.path.insert(0, parent_dir)
# ----------------------------------------------------

# 从主文件导入配置和核心函数
try:
    from dashboard import TARGETS, load_state, get_metrics_from_csv, find_latest_data_file, calculate_index_pl_metrics
except ImportError as e:
    st.error(f"导入主文件配置失败: {e}")
    st.info("请确保 dashboard.py 位于项目根目录，且代码已更新到最新版本。")
    st.stop()

# ================= 辅助函数 =================

def format_trade_history(history_list):
    """格式化交易历史列表为 DataFrame"""
    if not history_list:
        return pd.DataFrame()
        
    df = pd.DataFrame(history_list)
    if 'portions' not in df.columns: df['portions'] = 0
    
    df = df.rename(columns={
        'date': '成交日期', 'type': '操作类型', 'pe': '成交PE',
        'close': '成交点位', 'price': 'ETF成交价', 'unit': '交易份额'
    })
    
    df['成交日期'] = pd.to_datetime(df['成交日期']).dt.strftime('%Y-%m-%d')
    for col in ['成交PE', '成交点位', 'ETF成交价']:
        if col in df.columns:
            df[col] = df[col].apply(lambda x: f"{x:.4f}" if pd.notna(x) else 'N/A')
    
    return df.sort_values(by='成交日期', ascending=False)

def get_pl_color(pl_pct):
    if pl_pct > 0: return "normal"
    elif pl_pct < 0: return "inverse"
    return "off"

def plot_pe_close_combined(index_name, df_full, history_state):
    df_plot = df_full.copy()
    # 确保 Date 是 datetime 对象
    df_plot['Date'] = pd.to_datetime(df_plot['Date'])
    
    trade_df = pd.DataFrame(history_state)
    if not trade_df.empty:
        trade_df['date'] = pd.to_datetime(trade_df['date'])
    
    fig = make_subplots(specs=[[{"secondary_y": True}]])
    
    # PE
    fig.add_trace(go.Scatter(x=df_plot['Date'], y=df_plot['pe'], name='PE 走势 (左轴)', line=dict(color='blue', width=2)), secondary_y=False)
    
    # 均线 (V24.12: 恢复 avg_10yr)
    if 'avg_3yr' in df_plot.columns:
         fig.add_trace(go.Scatter(x=df_plot['Date'], y=df_plot['avg_3yr'], mode='lines', name='PE 3年均值', line={'dash': 'dash', 'color': 'gray', 'width': 3}), secondary_y=False)
    if 'avg_5yr' in df_plot.columns:
         fig.add_trace(go.Scatter(x=df_plot['Date'], y=df_plot['avg_5yr'], mode='lines', name='PE 5年均值', line={'dash': 'dot', 'color': 'lightgray', 'width': 3}), secondary_y=False)
    if 'avg_10yr' in df_plot.columns:
         fig.add_trace(go.Scatter(x=df_plot['Date'], y=df_plot['avg_10yr'], mode='lines', name='PE 10年均值', line={'dash': 'dot', 'color': 'red', 'width': 3}), secondary_y=False)

    # Close
    fig.add_trace(go.Scatter(x=df_plot['Date'], y=df_plot['Close'], name='点位走势 (右轴)', line=dict(color='orange', width=2)), secondary_y=True)

    # 交易点
    if not trade_df.empty:
        valid_trades = trade_df.dropna(subset=['pe', 'close'])
        buy = valid_trades[valid_trades['type'] == '买入']
        sell = valid_trades[valid_trades['type'] == '卖出']
        
        if not buy.empty:
             fig.add_trace(go.Scatter(x=buy['date'], y=buy['pe'], mode='markers', name='买入 PE', marker={'size': 10, 'symbol': 'triangle-up', 'color': 'green'}), secondary_y=False)
        if not sell.empty:
             fig.add_trace(go.Scatter(x=sell['date'], y=sell['pe'], mode='markers', name='卖出 PE', marker={'size': 10, 'symbol': 'triangle-down', 'color': 'red'}), secondary_y=False)

    fig.update_layout(title_text=f'📈 {index_name} PE与点位合并走势', height=550, hovermode="x unified")
    fig.update_yaxes(title_text="<b>PE-TTM</b>", secondary_y=False)
    fig.update_yaxes(title_text="<b>指数点位</b>", secondary_y=True)
    st.plotly_chart(fig, use_container_width=True)

# ================= 页面主体 =================

st.title("📊 交易分析与图表总览")
st.markdown("---")

state = load_state()
index_options = list(TARGETS.values())

selected_name = st.selectbox("选择指数：", index_options)
selected_file = [f for f, n in TARGETS.items() if n == selected_name][0]

prefix = selected_file.split('.')[0]
actual_file_path, _, _ = find_latest_data_file(prefix)

metrics_result = None
if actual_file_path:
    metrics_result = get_metrics_from_csv(actual_file_path)

if metrics_result:
    # V24.12: 解包并重置索引 (修复 KeyError)
    df_full = metrics_result[-1] 
    df_full = df_full.reset_index() 
    
    s = state.get(selected_file, {})
    history_state = s.get("history", [])
    
    # 本地计算指标
    current_close = df_full['Close'].iloc[-1]
    avg_cost, pl_pct, mkt_val = calculate_index_pl_metrics(s, current_close)
    holdings = s.get('holdings', 0.0)

    # --- 核心指标 ---
    st.subheader(f"💰 {selected_name} 持仓概览")
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("当前持仓份额", f"{holdings:.2f}")
    c2.metric("持仓市值", f"¥ {mkt_val:,.0f}")
    c3.metric("平均成本", f"¥ {avg_cost:.4f}" if holdings > 0 else "—")
    c4.metric("浮动盈亏", f"{pl_pct*100:.2f}%" if holdings > 0 else "—", 
              delta_color=get_pl_color(pl_pct) if holdings > 0 else "off")
    
    st.markdown("---")

    # --- 图表 ---
    st.subheader("📊 历史走势")
    
    df_full['Date'] = pd.to_datetime(df_full['Date'])
    
    min_d, max_d = df_full['Date'].min().date(), df_full['Date'].max().date()
    c_d1, c_d2 = st.columns(2)
    start_d = c_d1.date_input("开始", value=min_d, min_value=min_d, max_value=max_d)
    end_d = c_d2.date_input("结束", value=max_d, min_value=min_d, max_value=max_d)
    
    mask = (df_full['Date'].dt.date >= start_d) & (df_full['Date'].dt.date <= end_d)
    plot_pe_close_combined(selected_name, df_full.loc[mask], history_state)

    # --- 表格 ---
    st.subheader("📜 交易记录")
    history_df = format_trade_history(history_state)
    if not history_df.empty:
        st.dataframe(history_df, use_container_width=True, height=400)
    else:
        st.info("暂无记录")

else:
    if not actual_file_path:
        st.warning(f"未找到数据文件: {prefix}")
    else:
        st.error("数据加载失败，请检查文件格式。")
