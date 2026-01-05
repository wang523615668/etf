import streamlit as st
import pandas as pd
import plotly.graph_objects as go
from plotly.subplots import make_subplots
import requests
import time
import os
from datetime import datetime, timedelta

# ==================== 1. 页面配置 ====================
st.set_page_config(
    page_title="智能资产配置 Pro (完整版)",
    page_icon="💹",
    layout="wide",
    initial_sidebar_state="expanded"
)

# ==================== 2. 全局配置 ====================
DEFAULT_TOKEN = "71f8bc4a-2a8c-4a38-bc43-4bede4dba831"

MARKET_INDEX_CODE = "000985" 
MARKET_INDEX_NAME = "A股全指"

INDEX_MAP = {
    "沪深300": "000300", "上证50": "000016", "中证500": "000905", "创业板指": "399006",
    "科创50": "000688", "中证红利": "000922", "中证白酒": "399997", "中证医疗": "399989", 
    "中证传媒": "399971", "证券公司": "399975", "中证银行": "399986", "中证环保": "000827", 
    "全指消费": "000990", "全指医药": "000991", "全指金融": "000992", "全指信息": "000993", 
    "养老产业": "399812"
}

# 📂 数据保存路径
DATA_DIR = "market_data"
if not os.path.exists(DATA_DIR):
    os.makedirs(DATA_DIR)

# ==================== 3. 核心数据引擎 (智能缓存版) ====================

def fetch_chunk(token, url, payload_template, start_dt, end_dt):
    """API请求辅助函数"""
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

def fetch_from_api_incremental(token, code, years, local_df=None):
    """执行 API 增量/全量拉取"""
    end_date = datetime.now()
    
    # 计算目标起始时间
    if years > 10:
        target_start_date = datetime(2005, 1, 1)
    else:
        target_start_date = end_date - timedelta(days=years * 365 + 60)

    # 确定本次请求的起点
    if local_df is not None and not local_df.empty:
        local_start = local_df.index[0]
        # 如果本地数据够老（覆盖了目标起点），则只增量更新后面
        if local_start <= target_start_date + timedelta(days=30): 
            start_date = local_df.index[-1] + timedelta(days=1)
            is_incremental = True
        else:
            # 本地数据不足以覆盖历史，强制全量
            start_date = target_start_date
            is_incremental = False
    else:
        start_date = target_start_date
        is_incremental = False
            
    if start_date.date() > end_date.date():
        return local_df, "local_latest"

    url_fund = "https://open.lixinger.com/api/cn/index/fundamental"
    metrics_fund = ["pe_ttm.ewpvo", "pe_ttm.median", "pb.median"]
    payload_fund_tmpl = {"token": token, "stockCodes": [code], "metricsList": metrics_fund}
    
    url_kline = "https://open.lixinger.com/api/cn/index/candlestick"
    payload_kline_tmpl = {"token": token, "stockCode": code, "type": "normal", "qType": "1d"}

    CHUNK_DAYS = 3200 
    current_start = start_date
    df_fund_list = []
    df_kline_list = []
    
    try:
        while current_start < end_date:
            current_end = min(current_start + timedelta(days=CHUNK_DAYS), end_date)
            chunk_fund = fetch_chunk(token, url_fund, payload_fund_tmpl, current_start, current_end)
            if chunk_fund is not None and not chunk_fund.empty: df_fund_list.append(chunk_fund)
            
            chunk_kline = fetch_chunk(token, url_kline, payload_kline_tmpl, current_start, current_end)
            if chunk_kline is not None and not chunk_kline.empty: df_kline_list.append(chunk_kline)
                
            current_start = current_end + timedelta(days=1)
            time.sleep(0.05)

        if not df_fund_list: 
            return local_df, "no_new_data"
            
        df_fund_new = pd.concat(df_fund_list).drop_duplicates(subset=['date'])
        df_fund_new["date"] = pd.to_datetime(df_fund_new["date"]).dt.tz_localize(None)
        df_fund_new = df_fund_new.set_index("date").sort_index()
        
        if df_kline_list:
            df_kline_new = pd.concat(df_kline_list).drop_duplicates(subset=['date'])
            df_kline_new["date"] = pd.to_datetime(df_kline_new["date"]).dt.tz_localize(None)
            df_kline_new = df_kline_new.set_index("date")[["close"]]
            df_new = df_fund_new.join(df_kline_new, how="inner").sort_index()
        else:
            df_new = df_fund_new
            df_new["close"] = None

        rename_map = {
            "pe_ttm.ewpvo": "PE_正数等权", "pe_ttm.median": "PE_中位数",
            "pb.median": "PB_中位数", "close": "指数点位"
        }
        df_new = df_new.rename(columns=rename_map)
        for col in rename_map.values():
            if col in df_new.columns: df_new[col] = pd.to_numeric(df_new[col], errors='coerce')
            
        if is_incremental and local_df is not None:
            df_new = df_new[~df_new.index.isin(local_df.index)]
            df_final = pd.concat([local_df, df_new]).sort_index()
        else:
            df_final = df_new

        return df_final, "updated"
        
    except Exception as e:
        return local_df, f"Error: {str(e)}"

@st.cache_data(ttl=3600)
def get_smart_data(token, code, years, force_update=False):
    """
    智能数据获取器
    """
    idx_name = "未知"
    if code == MARKET_INDEX_CODE: idx_name = MARKET_INDEX_NAME
    else:
        found = [k for k, v in INDEX_MAP.items() if v == code]
        if found: idx_name = found[0]
    
    file_path = os.path.join(DATA_DIR, f"{idx_name}_{code}.csv")
    
    local_df = None
    if os.path.exists(file_path):
        try:
            local_df = pd.read_csv(file_path)
            local_df["date"] = pd.to_datetime(local_df["date"])
            local_df = local_df.set_index("date").sort_index()
        except:
            local_df = None

    # 检查本地历史是否足够
    data_is_sufficient = True
    if local_df is not None and not local_df.empty:
        local_start = local_df.index[0]
        if years > 10:
            req_start = datetime(2005, 1, 1)
        else:
            req_start = datetime.now() - timedelta(days=years * 365)
        
        if local_start > req_start + timedelta(days=60):
            data_is_sufficient = False
    else:
        data_is_sufficient = False

    today_str = datetime.now().strftime("%Y-%m-%d")
    
    if local_df is not None and not local_df.empty:
        last_date_str = local_df.index[-1].strftime("%Y-%m-%d")
        if last_date_str == today_str and not force_update and data_is_sufficient:
            return local_df, "local_cache_hit"
        if not force_update and data_is_sufficient:
             return local_df, "local_cache_old"

    df_final, status = fetch_from_api_incremental(token, code, years, local_df)
    
    if df_final is not None and not df_final.empty:
        df_final.to_csv(file_path, encoding='utf-8-sig')
        return df_final, status

    return local_df, "no_action"

# ==================== 4. 统计逻辑 (修正切片逻辑) ====================
def calculate_metrics(df, lookback_years):
    if df is None or df.empty: return None
    
    # 1. 确定分析窗口 (Slicing) - 修正分位点计算逻辑
    end_date = df.index[-1]
    if lookback_years > 10:
        start_date = datetime(2005, 1, 1)
    else:
        start_date = end_date - timedelta(days=lookback_years * 365)
        
    df_window = df[df.index >= start_date]
    if df_window.empty: df_window = df 
    
    latest = df.iloc[-1]
    res = {}
    
    pe_cur = latest.get("PE_正数等权", 0)
    pe_med_cur = latest.get("PE_中位数", 0)
    pb_cur = latest.get("PB_中位数", 0)
    
    res["当前点位"] = latest.get("指数点位", 0)
    res["当前PE"] = pe_cur
    res["当前PE_中位"] = pe_med_cur
    res["当前PB"] = pb_cur
    
    # 使用 Window 数据计算分位
    res["PE分位"] = (df_window["PE_正数等权"] < pe_cur).mean() * 100
    res["PE分位_中位"] = (df_window["PE_中位数"] < pe_med_cur).mean() * 100
    res["PB分位"] = (df_window["PB_中位数"] < pb_cur).mean() * 100
    
    # 均值 (客观指标，使用固定窗口)
    df_5y = df.iloc[-1250:] if len(df) > 1250 else df
    df_10y = df.iloc[-2500:] if len(df) > 2500 else df
    
    pe_avg_5y = df_5y["PE_正数等权"].mean()
    pe_avg_10y = df_10y["PE_正数等权"].mean()
    
    res["5年均PE"] = pe_avg_5y
    res["10年均PE"] = pe_avg_10y
    
    res["偏离5年(%)"] = (pe_cur - pe_avg_5y) / pe_avg_5y * 100
    res["偏离10年(%)"] = (pe_cur - pe_avg_10y) / pe_avg_10y * 100
    
    pct = res["PE分位"]
    if pct <= 10: res["操作建议"] = "💎 极低 (买入)"
    elif pct <= 30: res["操作建议"] = "🟢 偏低 (定投)"
    elif pct >= 90: res["操作建议"] = "⚠️ 极高 (清仓)"
    elif pct >= 70: res["操作建议"] = "🔴 偏高 (卖出)"
    else: res["操作建议"] = "⚖️ 正常 (持有)"
        
    return res

def scan_market(token, index_map, lookback_years, force_update):
    data = []
    prog = st.progress(0)
    status_box = st.empty()
    total = len(index_map)
    
    for i, (name, code) in enumerate(index_map.items()):
        status_box.text(f"正在读取: {name}...")
        prog.progress((i + 1) / total)
        
        df, status = get_smart_data(token, code, lookback_years, force_update)
        
        if df is not None:
            m = calculate_metrics(df, lookback_years)
            if m:
                data.append({
                    "指数": name,
                    "代码": code,
                    "PE(正等)": m['当前PE'],
                    "PE分位": m['PE分位'],
                    "操作建议": m['操作建议'], 
                    "偏离5年(%)": m['偏离5年(%)'], 
                    "5年均PE": m['5年均PE'],
                    "10年均PE": m['10年均PE'],
                    "PE(中位)": m['当前PE_中位'], 
                    "中位分位": m['PE分位_中位'],
                    "PB(中位)": m['当前PB'],
                    "PB分位": m['PB分位'], 
                })
        
        if force_update:
            time.sleep(0.05)
    
    prog.empty()
    status_box.empty()
    return pd.DataFrame(data)

# ==================== 5. 主界面逻辑 ====================
def main():
    st.title("🛡️ 智能财富仪表盘 Pro")
    
    if 'force_update_trigger' not in st.session_state:
        st.session_state['force_update_trigger'] = False

    with st.sidebar:
        st.header("⚙️ 参数")
        token = st.text_input("Token", value=DEFAULT_TOKEN, type="password")
        lookback = st.slider("估值分位参考周期 (年)", 3, 20, 10)
        st.caption("注：调整此年限，表格中的'PE分位'会随之变化。")
        
        st.markdown("---")
        st.markdown("### 📡 数据控制")
        st.info("默认优先读取本地数据 (省流模式)。\n如需获取最新行情，请点击下方按钮。")
        
        if st.button("🔄 手动更新数据 (消耗API)", type="primary"):
            st.session_state['force_update_trigger'] = True
            st.cache_data.clear()
            st.rerun()

    force_update = st.session_state['force_update_trigger']

    # ================= 模块 0: 市场总舵 =================
    st.markdown("### 🧭 市场总温度计 (A股全指)")
    
    df_market, status = get_smart_data(token, MARKET_INDEX_CODE, lookback, force_update)
    
    if force_update:
        st.toast("API 更新已触发...", icon="🔄")
        st.session_state['force_update_trigger'] = False 

    if df_market is not None:
        m_market = calculate_metrics(df_market, lookback)
        
        c1, c2, c3, c4 = st.columns(4)
        with c1: st.metric("当前点位", f"{m_market['当前点位']:.0f}", delta=f"{m_market['当前点位'] - df_market.iloc[-2]['指数点位']:.1f}")
        with c2: st.metric("PE (正数等权)", f"{m_market['当前PE']:.2f}", delta=f"{m_market['偏离10年(%)']:.1f}% (偏离10年)", delta_color="inverse")
        with c3: st.metric("PE (中位数)", f"{m_market['当前PE_中位']:.2f}", help="绿色虚线")
        with c4:
            pct_val = m_market['PE分位']
            delta_color = "normal"
            if pct_val < 20: delta_color = "off"
            elif pct_val > 80: delta_color = "inverse"
            st.metric(f"{'全历史' if lookback>10 else f'近{lookback}年'}分位", f"{pct_val:.1f}%", f"{m_market['操作建议'].split(' ')[1]}", delta_color=delta_color)
            
        with st.expander("查看 A股全指 历史走势", expanded=False):
            fig_m = go.Figure()
            fig_m.add_trace(go.Scatter(x=df_market.index, y=df_market["PE_正数等权"], name="PE(正等)", 
                                       line=dict(color='red', width=2), fill='tozeroy'))
            fig_m.add_trace(go.Scatter(x=df_market.index, y=df_market["PE_中位数"], name="PE(中位)", 
                                       line=dict(color='blue', width=2, dash='dash')))
            fig_m.update_layout(
                height=300, margin=dict(l=0, r=0, t=10, b=0), template="plotly_white", hovermode="x unified",
                yaxis=dict(tickmode='linear', tick0=9, dtick=5, range=[9, 109]) 
            )
            st.plotly_chart(fig_m, use_container_width=True)
    else:
        st.error("无法获取数据，请检查Token或网络，并尝试点击【手动更新数据】")

    st.markdown("---")

    # ================= 【已找回】全景对比图 =================
    st.markdown("### 🎢 全市场中位数估值巡礼")
    with st.expander("📊 点击加载所有指数中位数对比", expanded=False):
        if st.button("🚀 加载全景对比图"):
            with st.spinner("正在加载本地数据..."):
                fig_all = go.Figure()
                for name, code in INDEX_MAP.items():
                    # 这里复用 get_smart_data，优先读本地，很快
                    df_tmp, _ = get_smart_data(token, code, lookback, force_update=False)
                    if df_tmp is not None and not df_tmp.empty:
                        fig_all.add_trace(go.Scatter(
                            x=df_tmp.index, y=df_tmp["PE_中位数"], name=name, opacity=0.8, line=dict(width=1.5)
                        ))
                fig_all.update_layout(
                    title="全市场 PE(中位数) 历史走势大比拼",
                    yaxis=dict(tickmode='linear', tick0=9, dtick=5, range=[9, 109]),
                    height=600, hovermode="x unified", template="plotly_white", legend=dict(orientation="h", y=1.1)
                )
                st.plotly_chart(fig_all, use_container_width=True)

    st.markdown("---")

    # ================= 细分指数表格 =================
    st.subheader("📋 细分赛道数据透视")
    
    st.session_state['scan_df'] = scan_market(token, INDEX_MAP, lookback, force_update)
            
    if not st.session_state['scan_df'].empty:
        df_show = st.session_state['scan_df']
        
        def style_dataframe(df):
            def color_deviation(val):
                if isinstance(val, (int, float)):
                    color = '#E74C3C' if val > 0 else '#2ECC71'
                    return f'color: {color}; font-weight: bold'
                return ''

            def color_suggestion(val):
                if '买入' in val: color = '#2ECC71'
                elif '卖出' in val: color = '#E74C3C'
                elif '清仓' in val: color = '#C0392B'
                elif '定投' in val: color = '#27AE60'
                else: color = '#F39C12'
                return f'color: {color}; font-weight: bold'

            return df.style.map(color_deviation, subset=['偏离5年(%)'])\
                           .map(color_suggestion, subset=['操作建议'])\
                           .format({
                               "PE(正等)": "{:.2f}", "PE分位": "{:.1f}%", 
                               "PE(中位)": "{:.2f}", "中位分位": "{:.1f}%",
                               "5年均PE": "{:.2f}", "10年均PE": "{:.2f}",
                               "偏离5年(%)": "{:+.1f}%",
                               "PB(中位)": "{:.2f}", "PB分位": "{:.1f}%"
                           })

        st.dataframe(
            style_dataframe(df_show),
            column_config={
                "指数": st.column_config.TextColumn("指数", width="small", pinned=True),
                "操作建议": st.column_config.TextColumn("操作建议", width="small"),
                "偏离5年(%)": st.column_config.NumberColumn("偏离5年", help="红高绿低"),
            },
            use_container_width=True, height=600, hide_index=True
        )
    else:
        st.info("👈 数据加载中...")

    # ================= 深度透视 =================
    st.markdown("---")
    st.subheader("🔍 深度透视")
    
    c1, c2 = st.columns([1, 3])
    with c1:
        all_options = {MARKET_INDEX_NAME: MARKET_INDEX_CODE, **INDEX_MAP}
        sel_name = st.selectbox("选择指数", list(all_options.keys()))
        
        df_detail, _ = get_smart_data(token, all_options[sel_name], lookback, force_update)
        
        if df_detail is not None:
            m = calculate_metrics(df_detail, lookback)
            st.success(f"建议：{m['操作建议']}")
            st.metric("5年偏离度", f"{m['偏离5年(%)']:+.2f}%")
            st.metric("10年偏离度", f"{m['偏离10年(%)']:+.2f}%")
            st.metric("中位数PE", f"{m['当前PE_中位']:.2f}")

    with c2:
        if df_detail is not None:
            fig = make_subplots(specs=[[{"secondary_y": True}]])
            
            fig.add_trace(go.Scatter(x=df_detail.index, y=df_detail["PE_正数等权"], name="PE (正数等权)", line=dict(color="red", width=2.5)), secondary_y=False)
            fig.add_trace(go.Scatter(x=df_detail.index, y=df_detail["PE_中位数"], name="PE (中位数)", line=dict(color="blue", width=2, dash='dash')), secondary_y=False)
            
            df_detail['MA5'] = df_detail['PE_正数等权'].rolling(window=250*5).mean()
            fig.add_trace(go.Scatter(x=df_detail.index, y=df_detail["MA5"], name="5年均线", line=dict(color="orange", width=1.5, dash='dot')), secondary_y=False)
            
            df_detail['MA10'] = df_detail['PE_正数等权'].rolling(window=250*10).mean()
            fig.add_trace(go.Scatter(x=df_detail.index, y=df_detail["MA10"], name="10年均线", line=dict(color="black", width=1.5, dash='dot')), secondary_y=False)
            
            fig.add_trace(go.Scatter(x=df_detail.index, y=df_detail["指数点位"], name="指数点位", line=dict(color="#34495E", width=1), opacity=0.2), secondary_y=True)
            
            fig.update_layout(
                title=f"{sel_name} 估值深度透视", height=500, hovermode="x unified", template="plotly_white",
                yaxis=dict(title="PE 估值", tickmode='linear', tick0=9, dtick=5, range=[9, 109]),
                yaxis2=dict(title="指数点位", showgrid=False)
            )
            st.plotly_chart(fig, use_container_width=True)

if __name__ == "__main__":
    main()