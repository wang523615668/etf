import streamlit as st
import pandas as pd
import plotly.graph_objects as go
import requests
from datetime import datetime, timedelta

st.set_page_config(page_title="估值多维对比", layout="wide", page_icon="🆚")

# ==================== 1. API 配置 ====================
with st.sidebar:
    st.header("🔌 配置")
    token = st.text_input("Token", value="71f8bc4a-2a8c-4a38-bc43-4bede4dba831", type="password")
    code = st.text_input("指数代码", value="000300")
    years = st.slider("数据回溯(年)", 3, 20, 10)

# ==================== 2. API 获取逻辑 ====================
@st.cache_data(ttl=3600)
def get_compare_data(token, code, years):
    end = datetime.now()
    if years >= 20:
        start = datetime(2005, 1, 1) # 全数据模式
    else:
        start = end - timedelta(days=years*365 + 60)
    
    url = "https://open.lixinger.com/api/cn/index/fundamental"
    metrics = ["pe_ttm.ewpvo", "pe_ttm.median", "pe_ttm.mcw"]
    
    payload = {
        "token": token, "startDate": start.strftime("%Y-%m-%d"),
        "endDate": end.strftime("%Y-%m-%d"), "stockCodes": [code], "metricsList": metrics
    }
    
    try:
        res = requests.post(url, json=payload, headers={'Content-Type':'application/json'}).json()
        if res.get("code") == 1:
            df = pd.DataFrame(res['data'])
            if df.empty: return None
            df['date'] = pd.to_datetime(df['date']).dt.tz_localize(None)
            df = df.set_index('date').sort_index()
            return df.rename(columns={
                "pe_ttm.ewpvo": "PE(正数等权)",
                "pe_ttm.median": "PE(中位数)",
                "pe_ttm.mcw": "PE(加权)"
            })
    except Exception as e:
        st.error(f"API Error: {e}")
    return None

# ==================== 3. 绘图逻辑 ====================
st.title(f"🆚 {code} 估值算法大比拼")

df = get_compare_data(token, code, years)

if df is not None:
    st.success(f"数据获取成功 ({df.index.min().date()} ~ {df.index.max().date()})")
    
    normalize = st.checkbox("归一化 (从起点对比涨幅)", value=False)
    
    fig = go.Figure()
    cols = ["PE(正数等权)", "PE(中位数)", "PE(加权)"]
    colors = ["#2980B9", "#27AE60", "#E67E22"]
    
    for col, color in zip(cols, colors):
        s = df[col]
        if normalize and s.iloc[0] != 0:
            s = s / s.iloc[0]
            
        fig.add_trace(go.Scatter(
            x=s.index, y=s, name=col,
            line=dict(color=color, width=2)
        ))
        
    fig.update_layout(height=600, template="plotly_white", hovermode="x unified")
    st.plotly_chart(fig, use_container_width=True)
else:
    st.error("无法获取数据，请检查 Token 或 代码")
