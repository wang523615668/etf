# pages/1_📊_Trade_Analysis.py (V20.0 - 图表与详情合并)

import streamlit as st
import pandas as pd
import numpy as np
import plotly.graph_objects as go
from plotly.subplots import make_subplots
from datetime import datetime

# 从主文件导入配置和核心函数
try:
    # 导入所需的函数和配置
    from dashboard import TARGETS, load_state, get_metrics_from_csv, find_latest_data_file, get_full_index_metrics
except ImportError:
    st.error("导入主文件配置失败。请确保 dashboard.py 位于项目根目录。")
    st.stop()


# ====================================================================
# A. 交易详情和格式化函数 (来自 1_💰_Trade_Detail.py)
# ====================================================================

def format_trade_history(history_list):
    """格式化交易历史列表为 DataFrame"""
    if not history_list:
        return pd.DataFrame()
        
    df = pd.DataFrame(history_list)
    df = df.rename(columns={
        'date': '成交日期',
        'type': '操作类型',
        'pe': '成交PE',
        'close': '成交点位',
        'price': 'ETF成交价',
        'unit': '交易份数'
    })
    
    df['成交日期'] = pd.to_datetime(df['成交日期']).dt.strftime('%Y-%m-%d')
    # 使用 pd.notna 检查 NaN，并确保 x 不是 None
    df['成交PE'] = df['成交PE'].apply(lambda x: f"{x:.2f}" if pd.notna(x) and x is not None else 'N/A')
    df['成交点位'] = df['成交点位'].apply(lambda x: f"{x:.2f}" if pd.notna(x) and x is not None else 'N/A')
    df['ETF成交价'] = df['ETF成交价'].apply(lambda x: f"{x:.4f}" if pd.notna(x) and x is not None else 'N/A')
    
    df = df.sort_values(by='成交日期', ascending=False)
    
    return df

def get_pl_color(pl_pct):
    """根据浮动盈亏返回 Streamlit 的 Delta 颜色"""
    if pl_pct > 0:
        return "normal"  # 绿色
    elif pl_pct < 0:
        return "inverse" # 红色
    return "off"


# ====================================================================
# B. 合并图表函数 (来自 1_📈_Index_Charts.py)
# ====================================================================

def plot_pe_close_combined(index_name, df_full, history_state):
    """
    生成 PE 走势图和点位走势图的合并图，使用副坐标轴。
    PE 使用主 Y 轴 (左侧)。点位 (Close) 使用副 Y 轴 (右侧)。
    """
    
    df_plot = df_full.copy()
    df_plot['Date'] = pd.to_datetime(df_plot['Date'])

    trade_df = pd.DataFrame(history_state)
    if not trade_df.empty:
        trade_df['date'] = pd.to_datetime(trade_df['date'])
    
    # --- 创建带有副坐标轴的子图 ---
    fig = make_subplots(specs=[[{"secondary_y": True}]])
    
    # 1. PE 走势 (主 Y 轴 / 左侧)
    fig.add_trace(
        go.Scatter(x=df_plot['Date'], y=df_plot['pe'], name='PE 走势 (左轴)', 
                   line=dict(color='blue', width=2)),
        secondary_y=False,
    )
    
    # 添加 3年/5年均值线 (主 Y 轴)
    if 'avg_3yr_roll' in df_plot.columns:
         fig.add_trace(go.Scatter(x=df_plot['Date'], y=df_plot['avg_3yr_roll'], mode='lines', 
                                  name='PE 3年均值', line={'dash': 'dash', 'color': 'gray', 'width': 3}),
                       secondary_y=False)
    if 'avg_5yr_roll' in df_plot.columns:
         fig.add_trace(go.Scatter(x=df_plot['Date'], y=df_plot['avg_5yr_roll'], mode='lines', 
                                  name='PE 5年均值', line={'dash': 'dot', 'color': 'lightgray', 'width': 3}),
                       secondary_y=False)
    if 'avg_10yr_roll' in df_plot.columns:
         fig.add_trace(go.Scatter(x=df_plot['Date'], y=df_plot['avg_10yr_roll'], mode='lines', 
                                  name='PE 10年均值', line={'dash': 'dot', 'color': 'red', 'width': 3}),
                       secondary_y=False)




    # 2. 点位走势 (副 Y 轴 / 右侧)
    fig.add_trace(
        go.Scatter(x=df_plot['Date'], y=df_plot['Close'], name='点位走势 (右轴)', 
                   line=dict(color='orange', width=2)),
        secondary_y=True,
    )

    # 3. 交易标记 (Buy/Sell)
    if not trade_df.empty:
        trade_df_valid = trade_df.dropna(subset=['pe', 'close'])
        buy_trades = trade_df_valid[trade_df_valid['type'] == '买入']
        sell_trades = trade_df_valid[trade_df_valid['type'] == '卖出']
        
        # 标记在 PE 线上 (主 Y 轴)
        if not buy_trades.empty:
             fig.add_trace(go.Scatter(x=buy_trades['date'], y=buy_trades['pe'], mode='markers', name='买入 PE',
                                marker={'size': 12, 'symbol': 'triangle-up', 'color': 'lime', 'line': {'width': 2, 'color': 'green'}}),
                           secondary_y=False)

        # 标记在 点位 线上 (副 Y 轴)
        if not buy_trades.empty:
             fig.add_trace(go.Scatter(x=buy_trades['date'], y=buy_trades['close'], mode='markers', name='买入点位',
                                marker={'size': 12, 'symbol': 'triangle-up', 'color': 'green', 'line': {'width': 2, 'color': 'darkgreen'}}),
                           secondary_y=True)

        # 标记在 PE 线上 (主 Y 轴)
        if not sell_trades.empty:
             fig.add_trace(go.Scatter(x=sell_trades['date'], y=sell_trades['pe'], mode='markers', name='卖出 PE',
                                marker={'size': 12, 'symbol': 'triangle-down', 'color': 'red', 'line': {'width': 2, 'color': 'darkred'}}),
                           secondary_y=False)

        # 标记在 点位 线上 (副 Y 轴)
        if not sell_trades.empty:
             fig.add_trace(go.Scatter(x=sell_trades['date'], y=sell_trades['close'], mode='markers', name='卖出点位',
                                marker={'size': 12, 'symbol': 'triangle-down', 'color': 'firebrick', 'line': {'width': 2, 'color': 'darkred'}}),
                           secondary_y=True)
                           
    # --- 布局设置 ---
    fig.update_layout(
        title_text=f'📈 {index_name} PE与点位合并走势图',
        height=600,
        hovermode="x unified",
        legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1)
    )

    # 设置主 Y 轴 (左侧)
    fig.update_yaxes(title_text="<b>PE-TTM (左轴)</b>", secondary_y=False, showgrid=True, gridcolor='rgba(0,0,255,0.1)', color='blue')
    
    # 设置副 Y 轴 (右侧)
    fig.update_yaxes(title_text="<b>指数点位 (右轴)</b>", secondary_y=True, showgrid=False, color='orange')
    
    # 设置 X 轴
    fig.update_xaxes(title_text="日期")

    st.plotly_chart(fig, use_container_width=True)


# ====================================================================
# C. Streamlit 页面主体 (合并运行逻辑)
# ====================================================================

st.title("📊 交易分析与图表总览")
st.markdown("本页面集成了指数走势图 (PE/点位) 和详细交易历史记录，方便您全面分析。")
st.markdown("---")

state = load_state()
index_options = list(TARGETS.values())

# --- 1. 指数选择 ---
selected_name = st.selectbox("选择要查看的指数：", index_options)
selected_file = [f for f, n in TARGETS.items() if n == selected_name][0]

# --- 2. 数据加载 ---
prefix = selected_file.split('.')[0]
actual_file_path, _, _ = find_latest_data_file(prefix)
metrics_result = None

if actual_file_path:
    metrics_result = get_metrics_from_csv(actual_file_path)

if metrics_result:
    # 获取指标和完整数据框
    df_full = metrics_result[5]
    history_state = state.get(selected_file, {}).get("history", [])
    
    # 尝试获取当前持仓和盈亏数据 (需依赖 dashboard.py 的 metrics 计算)
    index_metrics = get_full_index_metrics(selected_file, state, {}) 

    # --- 3. 核心指标展示 (来自 1_💰_Trade_Detail.py) ---
    st.subheader(f"💰 {selected_name} 当前持仓概览")

    col1, col2, col3, col4 = st.columns(4)

    with col1:
        st.metric("当前持仓份数", value=index_metrics['holdings'])

    with col2:
        if not np.isnan(index_metrics['current_close']):
            st.metric("当前指数点位", value=f"{index_metrics['current_close']:.2f}")
        else:
            st.info("点位数据缺失")

    with col3:
        if not np.isnan(index_metrics['avg_cost']):
            st.metric("平均成本 (ETF估算)", value=f"¥ {index_metrics['avg_cost']:.4f}")
        else:
            st.info("无买入成本记录")

    with col4:
        if not np.isnan(index_metrics['pl_pct']):
            pl_pct_display = f"{index_metrics['pl_pct'] * 100:.2f}%"
            st.metric(
                "浮动盈亏 (%)", 
                value=pl_pct_display, 
                delta_color=get_pl_color(index_metrics['pl_pct']),
                delta=f"{index_metrics['pl_pct'] * 100:.2f}%"
            )
        else:
            st.info("无持仓或成本，无法计算盈亏")
    
    st.markdown("---")

    # --- 4. 走势图展示 (修改版：增加时间筛选) ---
    st.subheader("📊 历史走势分析")
    
    # 确保 Date 列是 datetime 类型 (为了筛选)
    df_full['Date'] = pd.to_datetime(df_full['Date'])
    min_date = df_full['Date'].min().date()
    max_date = df_full['Date'].max().date()

    # 创建两列用于放置日期选择器
    col_date1, col_date2 = st.columns([1, 1])
    with col_date1:
        start_date = st.date_input("开始日期", value=min_date, min_value=min_date, max_value=max_date)
    with col_date2:
        end_date = st.date_input("结束日期", value=max_date, min_value=min_date, max_value=max_date)

    # 根据日期筛选数据
    mask = (df_full['Date'].dt.date >= start_date) & (df_full['Date'].dt.date <= end_date)
    df_filtered = df_full.loc[mask]

    # 将筛选后的数据传给绘图函数
    if not df_filtered.empty:
        plot_pe_close_combined(selected_name, df_filtered, history_state)
    else:
        st.warning("所选时间段内无数据。")

    # --- 5. 交易历史表 (来自 1_💰_Trade_Detail.py) ---
    st.subheader("📜 交易历史记录")
    
    history_df = format_trade_history(history_state)
    
    if history_df.empty:
        st.info(f"该指数 ({selected_name}) 暂无交易记录。")
    else:
        st.dataframe(history_df, use_container_width=True, height=400)


else:
    if not actual_file_path:
        st.warning(f"找不到 {selected_name} 对应的数据文件 ({prefix}_*.csv)，请将文件放入 index_data 文件夹。")
    else:
        st.error(f"无法处理 {selected_name} 的数据，请检查文件内容。")
