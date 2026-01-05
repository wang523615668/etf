import streamlit as st
import pandas as pd
import requests
import time
from datetime import datetime, timedelta
import plotly.graph_objects as go

# ==================== 1. 页面配置 ====================
st.set_page_config(page_title="智能投顾 (Smart Advisor)", layout="wide", page_icon="🤖")

# ==================== 2. 全局配置 (独立运行版) ====================
DEFAULT_TOKEN = "71f8bc4a-2a8c-4a38-bc43-4bede4dba831"
MARKET_INDEX_CODE = "000985" # A股全指 - 市场风向标

# ==================== 3. API 核心逻辑 (复用分段请求逻辑) ====================
def fetch_chunk(token, url, payload_template, start_dt, end_dt):
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
def get_market_temperature(token, years=15):
    """获取A股全指数据，计算市场温度"""
    if not token or len(token) < 10: return None, "Token无效"
    
    end_date = datetime.now()
    # 强制拉取长周期数据以计算准确分位
    start_date = datetime(2005, 1, 1) 
    
    url_fund = "https://open.lixinger.com/api/cn/index/fundamental"
    metrics = ["pe_ttm.ewpvo", "pe_ttm.median"]
    payload_tmpl = {"token": token, "stockCodes": [MARKET_INDEX_CODE], "metricsList": metrics}
    
    CHUNK_DAYS = 3200
    current_start = start_date
    df_list = []
    
    try:
        while current_start < end_date:
            current_end = min(current_start + timedelta(days=CHUNK_DAYS), end_date)
            chunk = fetch_chunk(token, url_fund, payload_tmpl, current_start, current_end)
            if chunk is not None and not chunk.empty: df_list.append(chunk)
            current_start = current_end + timedelta(days=1)
            time.sleep(0.05)
            
        if not df_list: return None, "未获取到数据"
        
        df = pd.concat(df_list).drop_duplicates(subset=['date'])
        df["date"] = pd.to_datetime(df["date"]).dt.tz_localize(None)
        df = df.set_index("date").sort_index()
        
        # 重命名
        rename_map = {"pe_ttm.ewpvo": "PE_正数等权", "pe_ttm.median": "PE_中位数"}
        df = df.rename(columns=rename_map)
        for col in rename_map.values():
            if col in df.columns: df[col] = pd.to_numeric(df[col], errors='coerce')
            
        return df, "success"
    except Exception as e:
        return None, str(e)

# ==================== 4. 核心算法逻辑 ====================
def calculate_advice(df):
    if df is None or df.empty: return None
    latest = df.iloc[-1]
    
    pe_cur = latest["PE_正数等权"]
    
    # 计算历史百分位
    percentile = (df["PE_正数等权"] < pe_cur).mean() * 100
    
    # 核心策略：反脆弱仓位管理
    # 分位点越低(便宜)，仓位越重
    target_position = 100 - percentile
    
    # 投资建议文案
    if percentile < 20:
        signal = "💎 钻石底 (极度低估)"
        action = "大胆买入 / 保持高仓位"
        color = "green"
    elif percentile < 40:
        signal = "🟢 黄金坑 (低估)"
        action = "定投 / 分批加仓"
        color = "lightgreen"
    elif percentile > 80:
        signal = "⚠️ 泡沫顶 (极度高估)"
        action = "清仓 / 止盈离场"
        color = "red"
    elif percentile > 60:
        signal = "🔴 风险区 (高估)"
        action = "停止买入 / 分批减仓"
        color = "orange"
    else:
        signal = "⚖️ 平衡市 (正常)"
        action = "持有不动 / 按部就班"
        color = "gray"
        
    return {
        "当前PE": pe_cur,
        "历史分位": percentile,
        "建议仓位": target_position,
        "信号": signal,
        "操作": action,
        "颜色": color
    }

# ==================== 5. 主界面逻辑 ====================
st.title("🤖 智能投顾：资产配置计算器")
st.markdown("""
本模块基于 **A股全指 (000985)** 的全历史估值水位，为您提供**宏观择时**与**仓位管理**建议。
> **核心逻辑**：别人贪婪我恐惧，别人恐惧我贪婪。建议股票仓位 = 100% - 当前PE历史百分位。
""")

st.markdown("---")

# --- 侧边栏配置 ---
with st.sidebar:
    st.header("⚙️ 账户配置")
    token = st.text_input("Token", value=DEFAULT_TOKEN, type="password")
    
    st.subheader("💰 资产输入")
    total_capital = st.number_input("您的总投资资金 (元)", min_value=10000, value=100000, step=10000, help="计划投入股市的总本金")
    current_equity = st.number_input("当前已持仓市值 (元)", min_value=0, value=0, step=5000, help="当前手里股票/基金的总市值")
    
    if st.button("🔄 刷新市场数据", type="primary"):
        st.cache_data.clear()
        st.rerun()

# --- 核心计算 ---
with st.spinner("正在分析全市场估值水位..."):
    df_market, msg = get_market_temperature(token)

if df_market is not None:
    res = calculate_advice(df_market)
    
    # === 第一部分：市场诊断 ===
    st.subheader("1️⃣ 市场诊断书")
    c1, c2, c3 = st.columns(3)
    
    with c1:
        st.metric("A股全指 PE", f"{res['当前PE']:.2f}", help="代表全市场整体估值水平")
    with c2:
        pct = res['历史分位']
        delta_color = "inverse" if pct > 50 else "normal" # 低于50显示绿色(好事)，高于50显示红色
        st.metric("历史分位点", f"{pct:.2f}%", f"{res['信号']}", delta_color=delta_color)
    with c3:
        st.metric("🎯 理论建议仓位", f"{res['建议仓位']:.0f}%", f"{res['操作']}")

    # === 第二部分：个性化操作建议 ===
    st.markdown("---")
    st.subheader("2️⃣ 您的操作建议")
    
    target_equity = total_capital * (res['建议仓位'] / 100)
    diff = target_equity - current_equity
    
    col_res1, col_res2 = st.columns([2, 1])
    
    with col_res1:
        st.info(f"基于您的总资金 **{total_capital:,.0f} 元**，结合当前市场水位，建议配置如下：")
        
        # 仪表盘式展示
        fig_bar = go.Figure()
        fig_bar.add_trace(go.Bar(
            y=['资产配置'], x=[target_equity], name='股票/基金', orientation='h', 
            marker=dict(color='#2980B9'), text=f"{target_equity:,.0f}", textposition='auto'
        ))
        fig_bar.add_trace(go.Bar(
            y=['资产配置'], x=[total_capital - target_equity], name='现金/理财', orientation='h', 
            marker=dict(color='#BDC3C7'), text=f"{total_capital - target_equity:,.0f}", textposition='auto'
        ))
        fig_bar.update_layout(barmode='stack', height=150, margin=dict(l=0, r=0, t=30, b=0), title="建议资产配比")
        st.plotly_chart(fig_bar, use_container_width=True)
        
    with col_res2:
        st.markdown("#### ⚡ 调仓指令")
        if abs(diff) < total_capital * 0.05:
            st.success("✅ **保持现状**\n\n您的当前仓位与建议仓位基本匹配，无需大幅操作。")
        elif diff > 0:
            st.warning(f"📥 **建议买入**\n\n**{diff:,.0f} 元**\n\n市场处于低位，您的仓位不足，建议分批加仓。")
        else:
            st.error(f"📤 **建议卖出**\n\n**{abs(diff):,.0f} 元**\n\n市场水位偏高或您持仓过重，建议止盈回收现金。")

    # === 第三部分：历史验证 ===
    with st.expander("查看 A股全指 历史估值走势"):
        fig = go.Figure()
        fig.add_trace(go.Scatter(x=df_market.index, y=df_market["PE_正数等权"], fill='tozeroy', name='PE估值'))
        fig.update_layout(title="A股全指历史PE (正数等权)", height=400, template="plotly_white")
        st.plotly_chart(fig, use_container_width=True)

else:
    st.error(f"无法获取市场数据: {msg}")