# pages/2_📈_Performance_Analysis.py (V22.1 - 风险与收益评估)

import streamlit as st
import pandas as pd
import numpy as np
import plotly.express as px
import plotly.graph_objects as go
import os
import sys
from datetime import datetime, timedelta

# --- 导入核心数据和函数 (保持增强导入兼容性) ---
try:
    # ----------------------------------------------------
    # V22.1 增强修复：确保 Streamlit 页面能找到父目录的模块
    current_dir = os.path.dirname(os.path.abspath(__file__))
    parent_dir = os.path.abspath(os.path.join(current_dir, '..'))
    if parent_dir not in sys.path:
        sys.path.insert(0, parent_dir)
    # ----------------------------------------------------
    
    # 导入 V22.0 dashboard 模块中的函数
    from dashboard import TARGETS, load_state, get_metrics_from_csv, find_latest_data_file
except ImportError:
    st.error("无法导入 dashboard.py。请确保您的文件结构正确，且 dashboard.py 存在于项目根目录。")
    st.stop()

st.set_page_config(page_title="指数性能分析", layout="wide", page_icon="📈")

# ========================= 新增：风险与收益计算函数 (V22.1) =========================

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
    # 计算累计最大值 (峰值)
    cumulative_max = series.cummax()
    # 计算回撤 (当前值 / 累计最大值) - 1
    drawdown = (series / cumulative_max) - 1
    # 找出最大回撤
    max_drawdown = drawdown.min()
    return max_drawdown

# ========================= 辅助数据处理 (保持 V20.0 基础逻辑) =========================

@st.cache_data(ttl=3600)
def load_all_index_data():
    """加载所有指数的收盘价数据，并统一处理，用于性能对比。"""
    
    st.info("🔄 正在加载所有指数数据并进行统一处理，这可能需要一些时间...")
    data_dict = {}
    
    # ... (加载和合并数据逻辑，保持不变) ...
    for fixed_filename_key, name in TARGETS.items():
        prefix = fixed_filename_key.split('.')[0]
        actual_file_path, _, _ = find_latest_data_file(prefix)
        
        if actual_file_path and os.path.exists(actual_file_path):
            try:
                metrics_result = get_metrics_from_csv(actual_file_path)
                if metrics_result:
                    df = metrics_result[5]
                    df = df.rename(columns={'Date': 'date', 'Close': 'close'})
                    df['date'] = pd.to_datetime(df['date'], errors='coerce')
                    df['close'] = pd.to_numeric(df['close'], errors='coerce')
                    df = df.dropna(subset=['date', 'close']).set_index('date').sort_index()

                    data_dict[name] = df['close']

            except Exception as e:
                st.warning(f"加载 {name} 的数据时发生错误: {e}")
                
    if not data_dict:
        st.error("无法加载任何指数数据。请检查 DATA_DIR 和 CSV 文件。")
        return None

    combined_index = pd.Index([])
    for series in data_dict.values():
        combined_index = combined_index.union(series.index)
        
    combined_df = pd.DataFrame(index=combined_index)
    for name, series in data_dict.items():
        combined_df[name] = series
        
    combined_df = combined_df.ffill() 
    
    st.success(f"✅ 已成功加载 {len(data_dict)} 个指数数据。")
    return combined_df

def calculate_relative_return(df, start_date):
    """计算从起始日期开始的相对收益率 (基准化为1)。"""
    
    df_filtered = df[df.index >= start_date].copy()
    
    if df_filtered.empty:
        return pd.DataFrame()
        
    initial_values = df_filtered.iloc[0].replace(0, np.nan).dropna()
    
    if initial_values.empty:
        return pd.DataFrame()

    relative_returns = df_filtered.div(initial_values, axis=1)
    
    return relative_returns

# ========================= Streamlit App =========================

def app():
    st.header("📈 指数性能分析 (横向对比)")
    st.markdown("---")

    combined_df = load_all_index_data()

    if combined_df is None or combined_df.empty:
        st.warning("数据加载失败或数据集为空，无法进行分析。")
        return
        
    # --- 1. 用户选择 ---
    st.subheader("选择分析参数")
    
    col_index_select, col_date_select, col_period_select = st.columns([2, 1, 1])
    
    # 1.1 指数选择
    index_names = list(combined_df.columns)
    default_selection = index_names[:5] if len(index_names) >= 5 else index_names
    
    with col_index_select:
        selected_indices = st.multiselect(
            "选择要对比的指数 (最多10个):",
            index_names,
            default=default_selection,
            max_selections=10
        )
        
    if not selected_indices:
        st.warning("请至少选择一个指数进行分析。")
        return

    # 2.1 起始日期选择
    min_date = combined_df.index.min().date()
    max_date = combined_df.index.max().date()
    default_start_date = max_date - timedelta(days=365) # 默认从一年前开始
    
    with col_date_select:
        start_date = st.date_input(
            "自定义起始日期:",
            value=default_start_date if default_start_date > min_date else min_date,
            min_value=min_date,
            max_value=max_date
        )

    # 2.2 预设周期选择
    with col_period_select:
        period_options = {
            "自定义日期": None, "最近一年": 365, "最近三年": 365*3, 
            "最近五年": 365*5, "年初至今 (YTD)": 0
        }
        selected_period_label = st.selectbox("或选择预设周期:", list(period_options.keys()))
        
        if selected_period_label != "自定义日期":
            days = period_options[selected_period_label]
            if days is not None:
                if days == 0: # YTD
                    start_date = datetime(max_date.year, 1, 1).date()
                else:
                    start_date = max_date - timedelta(days=days)
                    start_date = start_date.date()
            
            col_date_select.date_input(
                "自定义起始日期:", 
                value=start_date, 
                min_value=min_date, 
                max_value=max_date, 
                key='fixed_date_view'
            )
            
    start_dt = datetime.combine(start_date, datetime.min.time())
    
    # --- 2. 计算相对收益率 ---
    df_subset = combined_df[selected_indices]
    df_returns = calculate_relative_return(df_subset, start_dt)

    if df_returns.empty:
        st.error(f"在 {start_date.strftime('%Y-%m-%d')} 之后没有有效数据，请调整起始日期。")
        return

    st.markdown("---")
    
    # --- 3. 性能走势图 (保持不变) ---
    st.subheader(f"1. 💰 收益率走势对比 ({start_date.strftime('%Y-%m-%d')} 至今)")
    
    fig = px.line(
        df_returns.reset_index(), 
        x='index', 
        y=df_returns.columns, 
        title='标准化收益率走势 (起始点为 1.0)'
    )
    
    fig.update_layout(
        xaxis_title="日期",
        yaxis_title="相对收益率 (基准化 1.0)",
        legend_title="指数",
        height=600,
        hovermode="x unified"
    )
    st.plotly_chart(fig, use_container_width=True)

    st.markdown("---")
    
    # --- 4. 汇总表格 (V22.1: 添加 CAGR 和 Max Drawdown) ---
    st.subheader("2. 📊 性能汇总 (风险与收益)")
    
    # 计算绝对收益率 (Total Return)
    last_row = df_returns.iloc[-1]
    start_row = df_returns.iloc[0] # 标准化为 1.0
    
    total_returns = (last_row - 1) * 100
    
    # 计算 Max Drawdown 和 CAGR
    max_drawdowns = {}
    cagr_results = {}
    
    # 计算周期天数
    delta_days = (df_returns.index.max() - df_returns.index.min()).days
    
    for index_name in selected_indices:
        # 使用标准化后的收益率曲线计算最大回撤
        max_drawdowns[index_name] = calculate_max_drawdown(df_returns[index_name]) * 100
        
        # 使用起始和结束时的标准化价格计算 CAGR
        start_val = start_row[index_name] 
        end_val = last_row[index_name]
        cagr_results[index_name] = calculate_cagr(start_val, end_val, delta_days) * 100
        
    summary_data = {
        "指数名称": selected_indices,
        "总收益 (%)": total_returns.values,
        "年化收益率 (CAGR %)": [cagr_results.get(name) for name in selected_indices],
        "最大回撤 (Max Drawdown %)": [max_drawdowns.get(name) for name in selected_indices]
    }
    
    df_summary = pd.DataFrame(summary_data).set_index('指数名称')
    
    # 格式化表格显示
    def highlight_max_min(s):
        # 突出显示 CAGR 和总收益的 Max/Min，以及 Max Drawdown 的 Min (最小回撤即表现最好)
        if s.name in ["总收益 (%)", "年化收益率 (CAGR %)"]:
            is_extreme = s == s.max()
        elif s.name == "最大回撤 (Max Drawdown %)":
             is_extreme = s == s.max() # 最大回撤越小越好，但这里突出最大的负数（最差表现）
        else:
             is_extreme = pd.Series([False] * len(s), index=s.index)

        return [
            'background-color: #d4edda; font-weight: bold' if v else ''
            for v in is_extreme
        ]

    st.dataframe(
        df_summary.style.format("{:.2f}").apply(highlight_max_min, axis=0),
        use_container_width=True
    )
    
    st.markdown("---")


if __name__ == "__main__":
    app()
