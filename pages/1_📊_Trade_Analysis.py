import streamlit as st
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import requests
import time
from datetime import datetime, timedelta

# ==================== 1. 页面基础配置 ====================
st.set_page_config(page_title="交易分析 (API版)", layout="wide")

# ✅ 【关键修复】在此处定义 DEFAULT_TOKEN，确保后面能用到
DEFAULT_TOKEN = "71f8bc4a-2a8c-4a38-bc43-4bede4dba831"

# 指数映射表
INDEX_MAP = {
    "A股全指": "000985", "沪深300": "000300", "上证50": "000016", "中证500": "000905", 
    "创业板指": "399006", "科创50": "000688", "中证红利": "000922", "中证白酒": "399997",
    "中证医疗": "399989", "中证传媒": "399971", "证券公司": "399975", "中证银行": "399986"
}

# ==================== 2. API 核心逻辑 (独立版) ====================
def fetch_chunk(token, url, payload_template, start_dt, end_dt):
    """请求单个时间片段"""
    payload = payload_template.copy()
    payload['startDate'] = start_dt.strftime("%Y-%m-%d")
    payload['endDate'] = end_dt.strftime("%Y-%m-%d")
    try:
        res = requests.post(url, json=payload, headers={'Content-Type': 'application/json'}, timeout=15)
        res_json = res.json()
        if res_json.get("code") == 1:
            return pd.DataFrame(res_json.get("data", []))
        return None
    except:
        return None

@st.cache_data(ttl=3600)
def get_market_data(token, code, years=5):
    """获取带分段逻辑的行情数据"""
    if not token or len(token) < 10: return None, "Token无效"
    
    end_date = datetime.now()
    # 自动判断：如果回溯超过10年，从2005年开始抓取
    if years > 10:
        start_date = datetime(2005, 1, 1)
    else:
        start_date = end_date - timedelta(days=years * 365 + 60)
        
    url_kline = "https://open.lixinger.com/api/cn/index/candlestick"
    payload_tmpl = {"token": token, "stockCode": code, "type": "normal", "qType": "1d"}
    
    CHUNK_DAYS = 3200 
    current_start = start_date
    df_list = []
    
    try:
        # 分段循环抓取
        while current_start < end_date:
            current_end = min(current_start + timedelta(days=CHUNK_DAYS), end_date)
            chunk = fetch_chunk(token, url_kline, payload_tmpl, current_start, current_end)
            if chunk is not None and not chunk.empty: df_list.append(chunk)
            current_start = current_end + timedelta(days=1)
            time.sleep(0.05)
            
        if not df_list: return None, "未获取到数据"
        
        # 合并数据
        df = pd.concat(df_list).drop_duplicates(subset=['date'])
        df["date"] = pd.to_datetime(df["date"]).dt.tz_localize(None)
        df = df.set_index("date").sort_index()
        
        # 只保留收盘价
        df = df[["close"]].rename(columns={"close": "指数点位"})
        df["指数点位"] = pd.to_numeric(df["指数点位"], errors='coerce')
        return df, "success"
    except Exception as e:
        return None, str(e)

# ==================== 3. 主界面逻辑 ====================
st.title("📊 交易信号与指数走势分析")

with st.sidebar:
    st.header("配置")
    # 这里使用的是上面定义的 DEFAULT_TOKEN，不会再报错了
    token = st.text_input("Token", value=DEFAULT_TOKEN, type="password")
    
    idx_name = st.selectbox("选择指数", list(INDEX_MAP.keys()))
    years = st.slider("回溯时间(年)", 3, 20, 5)
    code = INDEX_MAP[idx_name]
    
    uploaded_file = st.file_uploader("上传交易记录 (Excel/CSV)", type=['xlsx', 'csv'])

# 1. 获取行情数据
with st.spinner(f"正在拉取 {idx_name} 行情..."):
    df_market, msg = get_market_data(token, code, years=years)

if df_market is not None:
    st.success(f"行情获取成功 ({df_market.index.min().date()} ~ {df_market.index.max().date()})")
    
    # 2. 处理交易记录
    if uploaded_file:
        try:
            if uploaded_file.name.endswith('.csv'):
                df_trade = pd.read_csv(uploaded_file)
            else:
                df_trade = pd.read_excel(uploaded_file)
            
            # 清洗列名
            df_trade.columns = [c.strip() for c in df_trade.columns]
            # 模糊匹配日期列
            date_col = next((c for c in df_trade.columns if '日期' in c or 'Date' in c), None)
            
            if date_col:
                df_trade[date_col] = pd.to_datetime(df_trade[date_col])
                
                # 绘图：行情 + 买卖点
                fig = go.Figure()
                
                # 指数走势
                fig.add_trace(go.Scatter(
                    x=df_market.index, y=df_market["指数点位"],
                    name=f"{idx_name}走势", line=dict(color='gray', width=1)
                ))
                
                # 标记买卖点
                # 模糊匹配操作列 (如: 操作, 类型, Type)
                op_col = next((c for c in df_trade.columns if '操作' in c or 'Type' in c), None)
                if op_col:
                    buys = df_trade[df_trade[op_col].str.contains('买', na=False)]
                    sells = df_trade[df_trade[op_col].str.contains('卖', na=False)]
                    
                    fig.add_trace(go.Scatter(
                        x=buys[date_col], y=[df_market.loc[d]['指数点位'] if d in df_market.index else None for d in buys[date_col]],
                        mode='markers', name='买入', marker=dict(color='red', symbol='triangle-up', size=10)
                    ))
                    fig.add_trace(go.Scatter(
                        x=sells[date_col], y=[df_market.loc[d]['指数点位'] if d in df_market.index else None for d in sells[date_col]],
                        mode='markers', name='卖出', marker=dict(color='green', symbol='triangle-down', size=10)
                    ))
                
                fig.update_layout(title="交易点位复盘", height=500, template="plotly_white")
                st.plotly_chart(fig, use_container_width=True)
                
            else:
                st.warning("Excel中未找到日期列，请确保包含'日期'字样")
        except Exception as e:
            st.error(f"文件读取错误: {e}")
    else:
        # 无交易记录时只显示K线
        fig = px.line(df_market, x=df_market.index, y="指数点位", title=f"{idx_name} 历史走势")
        fig.update_layout(template="plotly_white")
        st.plotly_chart(fig, use_container_width=True)
else:
    st.error(f"无法获取行情数据: {msg}")
