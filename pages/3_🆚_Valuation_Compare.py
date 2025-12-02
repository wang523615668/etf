import streamlit as st
import pandas as pd
import plotly.graph_objects as go
import os
import sys
from datetime import datetime, timedelta

# --- 路径设置 ---
try:
    current_dir = os.path.dirname(os.path.abspath(__file__))
    parent_dir = os.path.abspath(os.path.join(current_dir, '..'))
    if parent_dir not in sys.path:
        sys.path.insert(0, parent_dir)
    from dashboard import find_latest_data_file, get_metrics_from_csv
except ImportError:
    st.error("环境配置错误：无法导入 dashboard.py")
    st.stop()

# 尝试导入 akshare
try:
    import akshare as ak
except ImportError:
    st.warning("⚠️ 检测到未安装 `akshare` 库，请运行 `pip install akshare --upgrade`。")
    st.stop()

st.set_page_config(page_title="估值多维对比", layout="wide", page_icon="🆚")

st.title("🆚 沪深300 估值算法大比拼 (锁定滚动PE)")
st.markdown("""
**本次对比集齐了市场主流的四种估值视角 (均采用 TTM/滚动算法)：**
1.  🔵 **本地数据**：您上传的 CSV (正数等权)。
2.  🟢 **中位数 (乐咕)**：`滚动市盈率中位数` - 最典型的股票水位。
3.  🟡 **等权 (乐咕)**：`等权滚动市盈率` - 全市场平均水位。
4.  🔴 **加权 (乐咕)**：`滚动市盈率` - 大盘股视角。
""")

# ==================== 1. 加载本地数据 ====================
@st.cache_data(ttl=600)
def load_local_hs300():
    """加载本地沪深300数据"""
    prefix = "沪深300"
    fpath, fname, _ = find_latest_data_file(prefix)
    
    if not fpath:
        return None, "未找到本地【沪深300】数据文件"
        
    metrics = get_metrics_from_csv(fpath)
    if not metrics:
        return None, "本地文件解析失败"
    
    # 兼容 dashboard.py 返回值
    df = metrics[-1].copy()
    
    if not isinstance(df.index, pd.DatetimeIndex):
        df.index = pd.to_datetime(df.index)
    
    return df.sort_index(), f"本地文件: {fname}"

# ==================== 2. 获取 AKShare 数据 (精确列名锁定) ====================
@st.cache_data(ttl=3600)
def fetch_multidim_data():
    """
    从乐咕 (Legu) 获取指数估值
    精准锁定 '滚动' (TTM) 相关列，排除 '静态'
    """
    data_dict = {}
    logs = []
    debug_info = None 
    
    try:
        # symbol="沪深300"
        df_lg = ak.stock_index_pe_lg(symbol="沪深300")
        
        if not df_lg.empty:
            debug_info = df_lg.head(3).to_dict()
            logs.append(f"🔍 接口返回列: {list(df_lg.columns)}")
        
        # 查找日期列
        date_col = next((c for c in df_lg.columns if "日期" in c or "date" in c.lower()), None)
        
        if date_col:
            df_lg['date'] = pd.to_datetime(df_lg[date_col])
            df_lg = df_lg.set_index('date').sort_index()
            
            # --- V3.6 核心修改：精确列名映射 ---
            # 直接使用您日志中出现的标准中文列名，不再模糊猜测
            
            # 1. 加权滚动市盈率 (官方标准)
            if '滚动市盈率' in df_lg.columns:
                data_dict['加权PE'] = df_lg['滚动市盈率']
            
            # 2. 等权滚动市盈率
            if '等权滚动市盈率' in df_lg.columns:
                data_dict['等权PE'] = df_lg['等权滚动市盈率']
            
            # 3. 中位数滚动市盈率
            if '滚动市盈率中位数' in df_lg.columns:
                data_dict['中位数PE'] = df_lg['滚动市盈率中位数']
            
            # 备用：万一列名带 TTM 英文
            if not data_dict:
                for col in df_lg.columns:
                    if "TTM" in str(col): # 只有当中文列名没找到时才启用 TTM 匹配
                        if "中位数" in str(col): data_dict['中位数PE'] = df_lg[col]
                        elif "等权" in str(col): data_dict['等权PE'] = df_lg[col]
                        else: data_dict['加权PE'] = df_lg[col]

            if data_dict:
                logs.append(f"✅ 成功锁定滚动PE数据: {list(data_dict.keys())}")
            else:
                logs.append("⚠️ 未找到任何 '滚动市盈率' 相关列，请检查接口返回。")
                
        else:
            logs.append("❌ 未找到日期列，无法解析。")
            
    except Exception as e:
        logs.append(f"❌ 乐咕接口调用失败: {str(e)}")
        
    return data_dict, logs, debug_info

# ==================== 3. 主页面逻辑 ====================

col_ctrl, col_chart = st.columns([1, 4])

with col_ctrl:
    st.subheader("⚙️ 控制台")
    lookback_years = st.slider("📅 回溯时间 (年)", 1, 10, 5)
    
    normalize_mode = st.checkbox("📏 归一化 (起点对齐)", value=False, help="将所有线条起点设为1.0，对比涨跌幅")
    
    if st.button("🚀 获取数据并对比", type="primary"):
        st.session_state['run_compare_v3'] = True

if st.session_state.get('run_compare_v3'):
    
    # 1. 准备数据
    df_local, local_name = load_local_hs300()
    
    with st.spinner("正在从乐咕(Legu)拉取滚动PE数据..."):
        online_data, fetch_logs, debug_table = fetch_multidim_data()
    
    # 显示日志
    with st.expander("查看接口日志", expanded=False):
        for log in fetch_logs:
            if "✅" in log: st.success(log)
            else: st.warning(log)
        if debug_table: st.json(debug_table)
    
    # 2. 绘图
    if df_local is None and not online_data:
        st.error("无法获取任何数据。")
        st.stop()
        
    with col_chart:
        title_suffix = " (归一化)" if normalize_mode else " (滚动PE绝对值)"
        st.subheader(f"📈 沪深300 估值全景 {title_suffix} (近 {lookback_years} 年)")
        
        fig = go.Figure()
        start_date = pd.Timestamp.now() - pd.DateOffset(years=lookback_years)
        
        # 辅助函数
        def process_series(s):
            s = pd.to_numeric(s, errors='coerce').dropna()
            s = s[s.index >= start_date]
            if normalize_mode and not s.empty:
                s = s / s.iloc[0]
            return s

        # A. 本地数据
        if df_local is not None:
            s = process_series(df_local['pe'])
            if not s.empty:
                fig.add_trace(go.Scatter(
                    x=s.index, y=s, name='🔵 本地 (正数等权)',
                    line=dict(color='#0052CC', width=4),
                    hovertemplate='%{y:.2f}'
                ))
            
        # B. 在线数据 (乐咕)
        colors = {'加权PE': '#E74C3C', '等权PE': '#F1C40F', '中位数PE': '#2ECC71'}
        styles = {'加权PE': 'solid', '等权PE': 'dash', '中位数PE': 'dot'}
        
        if online_data:
            for name, series in online_data.items():
                s = process_series(series)
                if s.empty: continue
                
                c = colors.get(name, 'gray')
                d = styles.get(name, 'solid')
                w = 2 if '加权' in name else 2
                
                fig.add_trace(go.Scatter(
                    x=s.index, y=s, name=f"{name} (乐咕)",
                    line=dict(color=c, width=w, dash=d),
                    hovertemplate='%{y:.2f}'
                ))

        fig.update_layout(
            xaxis_title="", yaxis_title="相对净值" if normalize_mode else "PE (TTM)",
            hovermode="x unified", height=600,
            legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1),
            template="plotly_white"
        )
        
        st.plotly_chart(fig, use_container_width=True)
        
        if not normalize_mode:
            st.info("""
            **🧐 数值解读：**
            * **加权PE (红线)**：通常**最低**。受大市值低估值股票影响最大。
            * **中位数PE (绿线)**：通常**居中**。代表市场最中间那个股票的估值，去除了极值干扰。
            * **等权PE (黄线)**：通常**最高**。受小盘股高估值影响较大。
            * **本地数据 (蓝线)**：通常介于中位数和等权之间（剔除了负值亏损股）。
            """)
