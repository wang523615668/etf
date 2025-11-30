# pages/2_📈_Performance_Analysis.py (V23.5 - 市场与持仓深度透视)

import streamlit as st
import pandas as pd
import numpy as np
import plotly.express as px
import os
import sys
from datetime import datetime, timedelta

# --- 导入核心数据和函数 ---
try:
    current_dir = os.path.dirname(os.path.abspath(__file__))
    parent_dir = os.path.abspath(os.path.join(current_dir, '..'))
    if parent_dir not in sys.path:
        sys.path.insert(0, parent_dir)
    
    # 导入 dashboard 中的配置和计算函数，确保逻辑一致
    from dashboard import TARGETS, load_state, get_metrics_from_csv, find_latest_data_file, calculate_index_pl_metrics
except ImportError:
    st.error("无法导入 dashboard.py。请确保您的文件结构正确，且 dashboard.py 存在于项目根目录。")
    st.stop()

st.set_page_config(page_title="指数性能与持仓分析", layout="wide", page_icon="📈")

# ========================= 核心指标计算函数 =========================

def calculate_cagr(start_price, end_price, days):
    """计算复合年均增长率 (CAGR)。"""
    if days == 0 or start_price == 0:
        return np.nan
    years = days / 365.25
    cagr = (end_price / start_price)**(1 / years) - 1
    return cagr

def calculate_max_drawdown(series):
    """计算最大回撤 (Max Drawdown)。"""
    if series.empty:
        return 0.0
    cumulative_max = series.cummax()
    drawdown = (series / cumulative_max) - 1
    max_drawdown = drawdown.min()
    return max_drawdown

# ========================= 数据加载 =========================

@st.cache_data(ttl=3600)
def load_all_index_data():
    """加载所有指数的收盘价数据，用于性能对比。"""
    
    st.info("🔄 正在加载并对齐所有指数数据...")
    data_dict = {}
    
    for fixed_filename_key, name in TARGETS.items():
        prefix = fixed_filename_key.split('.')[0]
        actual_file_path, _, _ = find_latest_data_file(prefix)
        
        if actual_file_path and os.path.exists(actual_file_path):
            try:
                metrics_result = get_metrics_from_csv(actual_file_path)
                if metrics_result:
                    df = metrics_result[5] # 获取 df_full
                    df = df.rename(columns={'Date': 'date', 'Close': 'close'})
                    df['date'] = pd.to_datetime(df['date'], errors='coerce')
                    df['close'] = pd.to_numeric(df['close'], errors='coerce')
                    df = df.dropna(subset=['date', 'close']).set_index('date').sort_index()

                    data_dict[name] = df['close']

            except Exception as e:
                st.warning(f"加载 {name} 时出错: {e}")
                
    if not data_dict:
        st.error("无法加载任何指数数据。")
        return None

    combined_index = pd.Index([])
    for series in data_dict.values():
        combined_index = combined_index.union(series.index)
        
    combined_df = pd.DataFrame(index=combined_index)
    for name, series in data_dict.items():
        combined_df[name] = series
        
    combined_df = combined_df.ffill() 
    
    st.success(f"✅ 成功加载 {len(data_dict)} 个指数。")
    return combined_df

def calculate_relative_return(df, start_date):
    """计算相对收益率 (归一化)。"""
    df_filtered = df[df.index >= start_date].copy()
    if df_filtered.empty: return pd.DataFrame()
    initial_values = df_filtered.iloc[0].replace(0, np.nan).dropna()
    if initial_values.empty: return pd.DataFrame()
    return df_filtered.div(initial_values, axis=1)

# ========================= Streamlit App =========================

def app():
    st.header("📈 指数性能与持仓深度透视")
    st.markdown("---")

    # 1. 加载所有市场数据
    combined_df = load_all_index_data()
    if combined_df is None or combined_df.empty:
        st.warning("无数据可分析。")
        return

    # 2. 加载用户持仓状态 (Portfolio State)
    state = load_state()
    
    # --- 用户交互区域 ---
    st.subheader("📊 分析参数")
    
    col_index, col_date, col_period = st.columns([2, 1, 1])
    
    all_names = list(combined_df.columns)
    
    # 默认选中所有有持仓的指数，或者前5个
    holdings_names = [TARGETS[k] for k, v in state.items() if v.get('holdings', 0) > 0 and TARGETS.get(k) in all_names]
    default_selection = holdings_names if holdings_names else all_names[:5]
    
    with col_index:
        selected_indices = st.multiselect("选择指数:", all_names, default=default_selection)
        
    if not selected_indices:
        st.warning("请选择至少一个指数。")
        return

    # 日期选择
    min_date = combined_df.index.min().date()
    max_date = combined_df.index.max().date()
    
    with col_period:
        period_options = {"最近一年": 365, "最近三年": 1095, "最近五年": 1825, "今年以来(YTD)": 0, "自定义": -1}
        selected_period = st.selectbox("时间周期:", list(period_options.keys()))
        
    with col_date:
        if selected_period == "自定义":
            start_date = st.date_input("开始日期:", value=max_date-timedelta(days=365), min_value=min_date, max_value=max_date)
        else:
            days = period_options[selected_period]
            if days == 0:
                start_date = datetime(max_date.year, 1, 1).date()
            else:
                start_date = max_date - timedelta(days=days)
                
            # 确保不早于数据开始
            if start_date < min_date: start_date = min_date
            st.date_input("开始日期 (自动):", value=start_date, disabled=True)

    start_dt = datetime.combine(start_date, datetime.min.time())
    
    # --- 计算市场表现 ---
    df_subset = combined_df[selected_indices]
    df_returns = calculate_relative_return(df_subset, start_dt)

    if df_returns.empty:
        st.error("选定范围内无有效数据。")
        return

    # --- 1. 走势图 ---
    st.markdown("---")
    st.subheader(f"📈 收益率走势对比 ({start_date} 至今)")
    
    fig = px.line(df_returns.reset_index(), x='index', y=df_returns.columns, title='累计收益率 (起始=1.0)')
    fig.update_layout(xaxis_title="日期", yaxis_title="净值", height=500, hovermode="x unified")
    st.plotly_chart(fig, use_container_width=True)

    # --- 2. 深度汇总表 (市场 + 持仓) ---
    st.markdown("---")
    st.subheader("💰 市场表现与持仓盈亏汇总")

    # 准备表格数据
    summary_list = []
    
    # 获取最后一天的数据用于计算
    last_row = df_returns.iloc[-1]
    start_row = df_returns.iloc[0]
    delta_days = (df_returns.index.max() - df_returns.index.min()).days
    
    # 反向映射：指数名称 -> 文件名Key (用于查 State)
    NAME_TO_KEY = {v: k for k, v in TARGETS.items()}

    for name in selected_indices:
        # A. 市场指标
        total_ret = (last_row[name] - 1) * 100
        max_dd = calculate_max_drawdown(df_returns[name]) * 100
        cagr = calculate_cagr(start_row[name], last_row[name], delta_days) * 100
        
        # B. 持仓指标 (从 State 获取)
        key = NAME_TO_KEY.get(name)
        user_data = state.get(key, {})
        
        holdings = user_data.get('holdings', 0.0)
        
        # 使用 dashboard 的函数计算精确盈亏
        # 注意：这里我们用当前的收盘价 (combined_df最后一行) 来估算
        current_close = combined_df[name].iloc[-1]
        
        # 调用 dashboard 的盈亏计算逻辑 (传入 df_full=None，因为该函数主要依赖 state 和 current_close)
        avg_cost, pl_pct, mkt_val = calculate_index_pl_metrics(user_data, current_close, None)
        
        # 格式化数据
        pl_val_display = np.nan
        if not np.isnan(pl_pct):
            pl_val_display = pl_pct * 100
            
        summary_list.append({
            "指数名称": name,
            "市场涨跌 (%)": total_ret,
            "最大回撤 (%)": max_dd,
            "年化收益 (CAGR %)": cagr,
            # 持仓数据
            "当前持仓 (份)": holdings,
            "持仓成本 (估)": avg_cost if holdings > 0 else np.nan,
            "持仓盈亏 (%)": pl_val_display
        })
    
    df_summary = pd.DataFrame(summary_list).set_index("指数名称")
    
    # --- 样式美化 ---
    def style_dataframe(df):
        return df.style.format({
            "市场涨跌 (%)": "{:+.2f}",
            "最大回撤 (%)": "{:.2f}",
            "年化收益 (CAGR %)": "{:+.2f}",
            "当前持仓 (份)": "{:.2f}",
            "持仓成本 (估)": "{:.4f}",
            "持仓盈亏 (%)": "{:+.2f}"
        }).applymap(lambda x: 'color: green; font-weight: bold' if x > 0 else ('color: red; font-weight: bold' if x < 0 else ''), 
                   subset=["市场涨跌 (%)", "年化收益 (CAGR %)", "持仓盈亏 (%)"]) \
          .applymap(lambda x: 'background-color: #f0f2f6' if x == 0 else '', subset=["当前持仓 (份)"])

    st.dataframe(style_dataframe(df_summary), use_container_width=True, height=400)
    
    st.caption("注：'持仓盈亏' 基于您记录的交易历史和当前指数点位估算，仅供参考。")

if __name__ == "__main__":
    app()
