import streamlit as st
import pandas as pd
import plotly.graph_objects as go
from plotly.subplots import make_subplots
import requests
import time
import os
import json
import re
from io import BytesIO, StringIO
from datetime import datetime, timedelta

# ==================== 1. 页面配置 ====================
st.set_page_config(
    page_title="智能资产配置 Pro (全景图定制版)",
    page_icon="💹",
    layout="wide",
    initial_sidebar_state="expanded"
)

# ==================== 2. 全局配置 ====================
DEFAULT_TOKEN = "71f8bc4a-2a8c-4a38-bc43-4bede4dba831"
TOKEN_FILE = "token.conf"
CUSTOM_INDEX_FILE = "custom_indices.json" 
TRADE_RECORD_FILE = "trade_records.json" 

MARKET_INDEX_CODE = "000985" 
MARKET_INDEX_NAME = "A股全指"

DEFAULT_INDEX_MAP = {
    "沪深300": "000300", "上证50": "000016", "中证500": "000905", "创业板指": "399006",
    "科创50": "000688", "中证红利": "000922", "中证白酒": "399997", "中证医疗": "399989", 
    "中证传媒": "399971", "证券公司": "399975", "中证银行": "399986", "中证环保": "000827", 
    "全指消费": "000990", "全指医药": "000991", "全指金融": "000992", "全指信息": "000993", 
    "养老产业": "399812"
}

DATA_DIR = "market_data"
if not os.path.exists(DATA_DIR):
    os.makedirs(DATA_DIR)

# ==================== 3. 基础函数库 ====================
def load_all_indices():
    indices = DEFAULT_INDEX_MAP.copy()
    if os.path.exists(CUSTOM_INDEX_FILE):
        try:
            with open(CUSTOM_INDEX_FILE, "r", encoding='utf-8') as f:
                indices.update(json.load(f))
        except: pass
    return indices

def save_custom_index(name, code):
    current = {}
    if os.path.exists(CUSTOM_INDEX_FILE):
        try:
            with open(CUSTOM_INDEX_FILE, "r", encoding='utf-8') as f:
                current = json.load(f)
        except: pass
    current[name] = code
    with open(CUSTOM_INDEX_FILE, "w", encoding='utf-8') as f:
        json.dump(current, f, ensure_ascii=False, indent=4)

def load_trade_records():
    if os.path.exists(TRADE_RECORD_FILE):
        try:
            with open(TRADE_RECORD_FILE, "r", encoding='utf-8') as f:
                return json.load(f)
        except: return []
    return []

def save_trade_record(date, op, idx):
    recs = load_trade_records()
    recs.append({"日期": date, "操作类型": op, "指数": idx, "timestamp": time.time()})
    with open(TRADE_RECORD_FILE, "w", encoding='utf-8') as f:
        json.dump(recs, f, ensure_ascii=False, indent=4)

INDEX_MAP = load_all_indices()

# ==================== 4. 数据获取核心 ====================
def get_token():
    if os.path.exists(TOKEN_FILE):
        try:
            with open(TOKEN_FILE, "r") as f:
                t = f.read().strip()
                if len(t) > 5: return t
        except: pass
    return DEFAULT_TOKEN

def save_token(new_token):
    with open(TOKEN_FILE, "w") as f:
        f.write(new_token.strip())

def fetch_chunk(token, url, payload, start, end):
    p = payload.copy()
    p['startDate'] = start.strftime("%Y-%m-%d")
    p['endDate'] = end.strftime("%Y-%m-%d")
    try:
        r = requests.post(url, json=p, headers={'Content-Type': 'application/json'}, timeout=10)
        if r.json().get("code") == 1:
            return pd.DataFrame(r.json().get("data", []))
        return None
    except: return None

@st.cache_data(ttl=3600*4)
def fetch_bond_yield(token):
    url = "https://open.lixinger.com/api/cn/macro/bond/yield"
    end_date = datetime.now()
    start_date = end_date - timedelta(days=90)
    payload = {
        "token": token, "areaCode": "cn",
        "startDate": start_date.strftime("%Y-%m-%d"),
        "endDate": end_date.strftime("%Y-%m-%d"),
        "metricsList": ["tcm_y10"]
    }
    try:
        res = requests.post(url, json=payload, headers={'Content-Type': 'application/json'}, timeout=5)
        data = res.json().get("data", [])
        if data:
            df = pd.DataFrame(data)
            df['date'] = pd.to_datetime(df['date'])
            df = df.sort_values('date') 
            return df.iloc[-1]['tcm_y10'] * 100
    except: pass
    return None

@st.cache_data(ttl=3600*4)
def fetch_usd_cny(token):
    url = "https://open.lixinger.com/api/cn/macro/fx/quote"
    end_date = datetime.now()
    start_date = end_date - timedelta(days=90)
    payload = {
        "token": token,
        "startDate": start_date.strftime("%Y-%m-%d"),
        "endDate": end_date.strftime("%Y-%m-%d"),
        "fromCurrency": "USD", "toCurrency": "CNY"
    }
    try:
        res = requests.post(url, json=payload, headers={'Content-Type': 'application/json'}, timeout=5)
        data = res.json().get("data", [])
        if data:
            df = pd.DataFrame(data)
            df['date'] = pd.to_datetime(df['date'])
            df = df.sort_values('date') 
            return df.iloc[-1]['close']
    except: pass
    return None

def fetch_incremental(token, code, years, local_df):
    end = datetime.now()
    start = datetime(2005, 1, 1) if years > 10 else end - timedelta(days=years * 365 + 60)
    
    if local_df is not None and not local_df.empty:
        if local_df.index[0] <= start + timedelta(30):
            start = local_df.index[-1] + timedelta(1)
        else: start = start 
    
    if start.date() > end.date(): return local_df, "latest"

    url_f = "https://open.lixinger.com/api/cn/index/fundamental"
    metrics = ["pe_ttm.ewpvo", "pe_ttm.median", "pb.median", "turnover_rate.ew"] 
    url_k = "https://open.lixinger.com/api/cn/index/candlestick"
    
    dfs_f, dfs_k = [], []
    curr = start
    while curr < end:
        next_end = min(curr + timedelta(3000), end)
        f_chunk = fetch_chunk(token, url_f, {"token": token, "stockCodes": [code], "metricsList": metrics}, curr, next_end)
        k_chunk = fetch_chunk(token, url_k, {"token": token, "stockCode": code, "type": "normal", "qType": "1d"}, curr, next_end)
        if f_chunk is not None: dfs_f.append(f_chunk)
        if k_chunk is not None: dfs_k.append(k_chunk)
        curr = next_end + timedelta(1)
        time.sleep(0.05)

    if not dfs_f: return local_df, "no_data"
    
    df_f = pd.concat(dfs_f).drop_duplicates('date')
    df_f['date'] = pd.to_datetime(df_f['date']).dt.tz_localize(None)
    df_f = df_f.set_index('date').sort_index()
    
    df_new = df_f
    if dfs_k:
        df_k = pd.concat(dfs_k).drop_duplicates('date')
        df_k['date'] = pd.to_datetime(df_k['date']).dt.tz_localize(None)
        df_k = df_k.set_index('date')[['close']] 
        df_new = df_f.join(df_k, how='inner')
    else:
        df_new['close'] = None

    cols = {
        "pe_ttm.ewpvo": "PE_正数等权", "pe_ttm.median": "PE_中位数", 
        "pb.median": "PB_中位数", "turnover_rate.ew": "换手率",
        "close": "指数点位"
    }
    df_new = df_new.rename(columns=cols)
    for c in cols.values(): 
        if c in df_new: df_new[c] = pd.to_numeric(df_new[c], errors='coerce')

    if local_df is not None:
        df_new = df_new[~df_new.index.isin(local_df.index)]
        return pd.concat([local_df, df_new]).sort_index(), "updated"
    return df_new, "new"

def get_smart_data(token, code, years, force):
    name = "未知"
    if code == MARKET_INDEX_CODE: name = MARKET_INDEX_NAME
    else: 
        matches = [k for k, v in INDEX_MAP.items() if v == code]
        if matches: name = matches[0]
            
    path = os.path.join(DATA_DIR, f"{name}_{code}.csv")
    local = None
    if os.path.exists(path):
        try: 
            local = pd.read_csv(path)
            local['date'] = pd.to_datetime(local['date'])
            local = local.set_index('date').sort_index()
        except: local = None

    is_sufficient = False
    req_start = datetime(2005, 1, 1) if years > 10 else datetime.now() - timedelta(days=years * 365 + 30)
    if local is not None and not local.empty:
        if local.index[0] <= req_start + timedelta(days=30):
            is_sufficient = True

    is_fresh = False
    if local is not None and not local.empty:
        if local.index[-1].strftime("%Y-%m-%d") == datetime.now().strftime("%Y-%m-%d"):
            is_fresh = True
    
    if is_fresh and is_sufficient and not force: return local, "cache"

    df, status = fetch_incremental(token, code, years, local)
    
    if df is not None and not df.empty:
        try: df.to_csv(path, encoding='utf-8-sig')
        except: pass
        return df, status
        
    return local_df, "no_action"

# ==================== 5. 核心打分引擎 (混合策略) ====================
def calc_indicators(df):
    if df is None or len(df) < 30: return df
    close = df['指数点位']
    df['BBI'] = (close.rolling(3).mean() + close.rolling(6).mean() + close.rolling(12).mean() + close.rolling(24).mean()) / 4
    ema12 = close.ewm(span=12, adjust=False).mean()
    ema26 = close.ewm(span=26, adjust=False).mean()
    df['DIF'] = ema12 - ema26
    df['DEA'] = df['DIF'].ewm(span=9, adjust=False).mean()
    df['MACD_Hist'] = (df['DIF'] - df['DEA']) * 2
    return df

def resample_weekly(df):
    if df is None: return None
    return df.resample('W-FRI').last().dropna()

def calculate_score(df_day, lookback, bond_yield=None):
    if df_day is None or df_day.empty: return None
    
    latest = df_day.iloc[-1]
    pe_cur = latest.get("PE_正数等权", 0)
    pb_cur = latest.get("PB_中位数", 0)
    pe_med_cur = latest.get("PE_中位数", 0)
    to_cur = latest.get("换手率", 0)
    
    start_dt = datetime(2005,1,1) if lookback > 10 else df_day.index[-1] - timedelta(days=lookback*365)
    hist = df_day[df_day.index >= start_dt]
    
    if hist.empty: return None

    pe_pct = (hist["PE_正数等权"] < pe_cur).mean() * 100
    pb_pct = (hist["PB_中位数"] < pb_cur).mean() * 100
    to_pct = (hist["换手率"] < to_cur).mean() * 100 if "换手率" in hist else 50
    
    df_5y = df_day.iloc[-1250:] if len(df_day) > 1250 else df_day
    df_10y = df_day.iloc[-2500:] if len(df_day) > 2500 else df_day
    pe_avg_5y = df_5y["PE_正数等权"].mean()
    pe_avg_10y = df_10y["PE_正数等权"].mean()
    
    dev_5y = (pe_cur - pe_avg_5y) / pe_avg_5y * 100 if pe_avg_5y else 0
    dev_10y = (pe_cur - pe_avg_10y) / pe_avg_10y * 100 if pe_avg_10y else 0
    
    df_week = resample_weekly(df_day.copy())
    df_week = calc_indicators(df_week)
    wk_now = df_week.iloc[-1] if len(df_week) >= 2 else None
    
    score = 0
    reasons = []
    
    if pe_pct <= 10: score += 60; reasons.append("💎 极低估")
    elif pe_pct <= 20: score += 50; reasons.append("🟢 低估")
    elif pe_pct <= 40: score += 30
    elif pe_pct >= 80: score -= 30; reasons.append("⚠️ 高估")
    elif pe_pct >= 60: score -= 10
        
    if wk_now is not None:
        if wk_now['指数点位'] > wk_now['BBI']: score += 20; reasons.append("📈 趋势好")
        if wk_now['DIF'] > wk_now['DEA']: score += 10; reasons.append("🔥 金叉")
            
    erp = 0
    if bond_yield and pe_cur > 0:
        erp = (1/pe_cur*100) - bond_yield
        if erp > 3.0: score += 10; reasons.append(f"💰 赔率高")
            
    if to_pct < 10: score += 5
    if to_pct > 90: score -= 5

    signal = "⚖️ 观望"
    if score >= 85: signal = "🚀 趋势共振"
    elif score >= 60: signal = "📉 左侧建仓"
    elif score <= 20: signal = "❄️ 减仓/回避"
    
    return {
        "当前点位": latest.get("指数点位", 0),
        "PE": pe_cur, "PE分位": pe_pct, 
        "PB": pb_cur, "PB分位": pb_pct,
        "5年均PE": pe_avg_5y, "10年均PE": pe_avg_10y, "PE(中位)": pe_med_cur,
        "偏离5年": dev_5y, "偏离10年": dev_10y,
        "总分": score, "信号": signal, "理由": " | ".join(reasons)
    }

def scan_market_with_score(token, indices, lookback, force, bond_yield):
    res = []
    prog = st.progress(0)
    msg = st.empty()
    
    for i, (name, code) in enumerate(indices.items()):
        msg.text(f"正在分析: {name} (周期{lookback}年)...")
        prog.progress((i)/len(indices))
        df, _ = get_smart_data(token, code, lookback, force)
        
        if df is not None:
            s = calculate_score(df, lookback, bond_yield)
            if s:
                res.append({
                    "指数": name, "代码": code,
                    "得分": s['总分'], "决策": s['信号'],
                    "当前PE": s['PE'], "PE分位": s['PE分位'],
                    "5年均PE": s['5年均PE'], "10年均PE": s['10年均PE'], "PE(中位)": s['PE(中位)'],
                    "偏离5年(%)": s['偏离5年'], "偏离10年(%)": s['偏离10年'],
                    "PB(中位)": s['PB'], "PB分位": s['PB分位'],
                    "分析": s['理由']
                })
        time.sleep(0.02)
        
    prog.empty()
    msg.empty()
    return pd.DataFrame(res)

# ==================== 6. 主界面 ====================
def main():
    st.title("🛡️ 智能资产配置 Pro (全能修正版)")
    
    # ✅ 1. 会话状态管理：保存上传/粘贴的交易记录
    if 'uploaded_trades' not in st.session_state:
        st.session_state['uploaded_trades'] = pd.DataFrame()
    if 'force' not in st.session_state: st.session_state['force'] = False

    with st.sidebar:
        st.header("⚙️ 控制台")
        
        # ✅ 功能1：更换 Token
        with st.expander("🔑 API Token 管理", expanded=False):
            current_token = get_token()
            masked = current_token[:4] + "*"*10 + current_token[-4:] if len(current_token)>10 else "未配置"
            st.text(f"当前: {masked}")
            new_token_input = st.text_input("输入新 Token", type="password")
            if st.button("💾 保存 Token"):
                if len(new_token_input) > 10:
                    save_token(new_token_input)
                    st.success("已保存，请刷新")
                    time.sleep(1)
                    st.rerun()
                else: st.error("Token 无效")

        # ✅ 修正：默认回溯周期改为12年
        lookback = st.slider("估值参考周期(年)", 3, 20, 12)
        
        if 'last_lookback' not in st.session_state:
            st.session_state['last_lookback'] = lookback
        if st.session_state['last_lookback'] != lookback:
            st.session_state['force'] = True
            st.session_state['last_lookback'] = lookback

        st.markdown("---")
        with st.expander("📝 手工记账", expanded=False):
            rec_date = st.date_input("交易日期")
            rec_idx = st.selectbox("交易指数", list(INDEX_MAP.keys()))
            rec_op = st.selectbox("操作", ["买入", "卖出"])
            if st.button("💾 记录"):
                save_trade_record(rec_date.strftime("%Y-%m-%d"), rec_op, rec_idx)
                st.toast(f"已记录")

        with st.expander("➕ 添加新指数", expanded=False):
            new_name = st.text_input("指数名称", placeholder="例如: 纳指100")
            new_code = st.text_input("指数代码", placeholder="例如: NDX")
            if st.button("确认添加"):
                if new_name and new_code:
                    save_custom_index(new_name, new_code)
                    st.success(f"已添加 {new_name}")
                    time.sleep(1)
                    st.rerun()

        st.markdown("---")
        st.markdown("### 🌍 宏观天眼")
        token = get_token()
        auto_bond = fetch_bond_yield(token)
        auto_usd = fetch_usd_cny(token)
        
        default_bond = auto_bond if auto_bond else 2.25
        default_usd = auto_usd if auto_usd else 7.00
        
        macro_bond = st.number_input("CN 10年国债 (%)", value=float(default_bond), step=0.01)
        macro_usd = st.number_input("USD/CNY 汇率", value=float(default_usd), step=0.01)
        
        st.markdown("---")
        if st.button("🔄 全量刷新数据", type="primary"):
            st.session_state['force'] = True
            st.cache_data.clear()
            st.rerun()
            
        st.markdown("---")
        # ✅ 功能2：交易导入 (存入 Session 确保不丢)
        with st.expander("📂 交易导入 (Excel/CSV)", expanded=True):
            pasted = st.text_area("粘贴数据 (自动保存到会话)", height=100)
            if st.button("📥 确认粘贴"):
                if pasted:
                    try:
                        # 尝试多种解析方式
                        try:
                            # 1. 有表头
                            df_paste = pd.read_csv(StringIO(pasted), sep=None, engine='python')
                            # 简单检查第一行是否像日期，如果像，说明没表头
                            if len(df_paste) > 0 and isinstance(df_paste.columns[0], str) and re.match(r'\d{4}', df_paste.columns[0]):
                                df_paste = pd.read_csv(StringIO(pasted), sep=None, engine='python', header=None)
                                df_paste.columns = ['日期', '操作类型', '指数']
                        except:
                            # 2. 兜底无表头
                            df_paste = pd.read_csv(StringIO(pasted), sep=None, engine='python', header=None)
                            df_paste.columns = ['日期', '操作类型', '指数']
                            
                        st.session_state['uploaded_trades'] = df_paste
                        st.success(f"已加载 {len(df_paste)} 条")
                    except Exception as e: st.error(f"失败: {e}")
            
            uploaded = st.file_uploader("上传文件 (自动保存)", type=['xlsx','csv'])
            if uploaded:
                try:
                    try: df_up = pd.read_excel(uploaded)
                    except: 
                        uploaded.seek(0)
                        encs = ['utf-8', 'gbk', 'gb18030']
                        for enc in encs:
                            try:
                                uploaded.seek(0)
                                df_up = pd.read_csv(uploaded, encoding=enc, on_bad_lines='skip')
                                if df_up.shape[1]>1: break
                            except: continue
                    st.session_state['uploaded_trades'] = df_up
                except: pass
            
            # 显示状态
            if not st.session_state['uploaded_trades'].empty:
                st.caption(f"💾 当前会话已暂存 {len(st.session_state['uploaded_trades'])} 条记录")
                if st.button("💾 永久保存到账本文件"):
                    # 写入 JSON
                    new_recs = st.session_state['uploaded_trades'].to_dict('records')
                    curr = load_trade_records()
                    # 清洗
                    clean_news = []
                    for r in new_recs:
                        cr = {}
                        for k,v in r.items():
                            k_s = str(k).strip()
                            if "指数" in k_s: cr["指数"]=str(v).strip()
                            elif "操作" in k_s: cr["操作类型"]=str(v).strip()
                            elif "日期" in k_s: 
                                # 强制转字符串
                                if isinstance(v, (pd.Timestamp, datetime)):
                                    cr["日期"]=v.strftime("%Y-%m-%d")
                                else: cr["日期"]=str(v).strip()
                            else: cr[k_s] = v
                        if "指数" in cr: clean_news.append(cr)
                    
                    curr.extend(clean_news)
                    with open(TRADE_RECORD_FILE, "w", encoding='utf-8') as f:
                        json.dump(curr, f, ensure_ascii=False, indent=4)
                    st.success("保存成功！")

    force = st.session_state['force']

    # --- 宏观面板 ---
    c1, c2, c3 = st.columns([1, 1, 2])
    with c1: 
        bond_delta = "平稳"
        if macro_bond > 3.0: bond_delta = "⚠️ 利率高"
        elif macro_bond < 2.5: bond_delta = "💧 流动性好"
        st.metric("无风险利率 (10Y)", f"{macro_bond:.2f}%", bond_delta, delta_color="inverse")
    with c2:
        usd_delta = "稳定"
        if macro_usd > 7.3: usd_delta = "⚠️ 汇率贬值"
        st.metric("USD/CNY", f"{macro_usd:.4f}", usd_delta, delta_color="inverse")
    with c3:
        env_score = "🌤️ 宏观中性"
        if macro_bond < 2.6 and macro_usd < 7.3: env_score = "☀️ 宏观顺风 (利多权益)"
        elif macro_bond > 3.2: env_score = "🌧️ 宏观逆风"
        st.info(f"**{env_score}** | 混合策略：低估买入，趋势加仓")

    st.markdown("---")

    # --- ✅ 复活：全景巡礼 (不限核心，遍历所有) ---
    st.subheader("🎢 全市场中位数估值巡礼 (全景图)")
    with st.expander("📊 点击展开/收起 全景对比图", expanded=False):
        if st.button("🚀 加载全景对比 (所有指数)"):
            with st.spinner("正在加载全市场数据..."):
                fig_all = go.Figure()
                for name, code in INDEX_MAP.items():
                    df_tmp, _ = get_smart_data(token, code, lookback, False)
                    if df_tmp is not None and not df_tmp.empty:
                        fig_all.add_trace(go.Scatter(x=df_tmp.index, y=df_tmp["PE_中位数"], name=name, line=dict(width=1.5)))
                
                # ✅ 修正：Y轴锁定
                fig_all.update_layout(height=600, title=f"全市场 PE(中位数) 走势对比 ({lookback}年)", template="plotly_white")
                fig_all.update_yaxes(range=[0, 90], dtick=5, title="PE (TTM) 中位数")
                
                st.plotly_chart(fig_all, use_container_width=True)

    st.markdown("---")

    # --- 综合榜单 (全指标) ---
    st.subheader(f"📊 机会扫描 ({lookback}年周期)")
    if 'scan_res' not in st.session_state or force:
        with st.spinner(f"正在重算 {lookback} 年维度估值分位..."):
            st.session_state['scan_res'] = scan_market_with_score(token, INDEX_MAP, lookback, force, macro_bond)
        st.session_state['force'] = False
    
    df_scan = st.session_state['scan_res']
    
    if not df_scan.empty:
        def style_df(df):
            def color_score(v):
                if v >= 85: return 'color: #2ECC71; font-weight: bold'
                if v >= 60: return 'color: #3498DB; font-weight: bold'
                if v <= 20: return 'color: #E74C3C'
                return 'color: #F39C12'
            def color_dev(v):
                if v > 0: return 'color: #E74C3C' 
                return 'color: #2ECC71' 
            
            return df.style.map(color_score, subset=['得分'])\
                           .map(color_dev, subset=['偏离5年(%)', '偏离10年(%)'])\
                           .format("{:.2f}", subset=['当前PE','5年均PE','10年均PE','PE(中位)','PB(中位)'])\
                           .format("{:.1f}", subset=['得分','PE分位','PB分位'])\
                           .format("{:+.1f}%", subset=['偏离5年(%)', '偏离10年(%)'])
        
        df_show = df_scan.sort_values("得分", ascending=False)
        st.dataframe(
            style_df(df_show),
            column_config={
                "指数": st.column_config.TextColumn("指数", width="small", pinned=True),
                "得分": st.column_config.NumberColumn("得分", help="满分100"),
                "决策": st.column_config.TextColumn("建议", width="small"),
                "分析": st.column_config.TextColumn("核心逻辑", width="large"),
                "PE分位": st.column_config.NumberColumn("PE分位", format="%.1f%%"),
                "PB分位": st.column_config.NumberColumn("PB分位", format="%.1f%%"),
            }, use_container_width=True, height=500, hide_index=True
        )
    else:
        st.info("👈 请点击刷新按钮")

    # --- 深度透视 ---
    st.markdown("---")
    st.subheader("🔍 深度透视")
    
    with st.expander("🛠️ 为什么买卖点没显示？点击自查", expanded=False):
        st.info("💡 系统正在尝试模糊匹配您的交易记录...")
        st.write("1. **系统当前选中的指数名称**:", st.session_state.get('last_sel_name', '未选择'))
        if not st.session_state['uploaded_trades'].empty:
            sample_names = st.session_state['uploaded_trades'].iloc[:, 2].unique()[:10] 
            st.write("2. **您上传文件中的指数名称 (前10个)**:", sample_names)
        else:
            st.write("2. **您尚未上传文件或粘贴数据**")

    c_sel, c_chart = st.columns([1, 3])
    with c_sel:
        sel_name = st.selectbox("选择指数", list({MARKET_INDEX_NAME: MARKET_INDEX_CODE, **INDEX_MAP}.keys()))
        st.session_state['last_sel_name'] = sel_name
        period = st.radio("周期", ["日线", "周线"], horizontal=True)
        view_mode = st.radio("视图模式", ["估值分析 (PE/PB通道)", "技术分析 (趋势/买卖)"], index=0)
        
        code = MARKET_INDEX_CODE if sel_name == MARKET_INDEX_NAME else INDEX_MAP[sel_name]
        df_raw, _ = get_smart_data(token, code, lookback, False)
        
        if df_raw is not None:
            score_res = calculate_score(df_raw, lookback, macro_bond)
            if score_res:
                st.metric("综合得分", f"{score_res['总分']}", score_res['信号'])
                st.caption(f"因子: {score_res['理由']}")
                st.divider()
                st.metric("当前PE", f"{score_res['PE']:.2f}", f"分位: {score_res['PE分位']:.1f}%")
                st.metric("5年偏离", f"{score_res['偏离5年']:+.1f}%", delta_color="inverse")
                st.metric("10年偏离", f"{score_res['偏离10年']:+.1f}%", delta_color="inverse")
                
    with c_chart:
        if df_raw is not None:
            df_plot = df_raw.copy()
            if period == "周线": df_plot = resample_weekly(df_plot)
            df_plot = calc_indicators(df_plot)
            
            if "技术" in view_mode:
                fig = make_subplots(rows=3, cols=1, shared_xaxes=True, row_heights=[0.6, 0.2, 0.2], vertical_spacing=0.03,
                                    subplot_titles=(f"{sel_name} 价格 & BBI", "MACD", "换手率"))
                
                # ✅ 实线
                fig.add_trace(go.Scatter(x=df_plot.index, y=df_plot["指数点位"], name="价格", line=dict(color="#2C3E50", width=1.5)), row=1, col=1)
                if "BBI" in df_plot.columns:
                    fig.add_trace(go.Scatter(x=df_plot.index, y=df_plot["BBI"], name="BBI均线", line=dict(color="#8E44AD", width=1.5)), row=1, col=1)
                
                if "DIF" in df_plot.columns:
                    fig.add_trace(go.Scatter(x=df_plot.index, y=df_plot["DIF"], name="DIF", line=dict(color="#E67E22", width=1), showlegend=False), row=2, col=1)
                    fig.add_trace(go.Scatter(x=df_plot.index, y=df_plot["DEA"], name="DEA", line=dict(color="#3498DB", width=1), showlegend=False), row=2, col=1)
                    colors = ['#2ECC71' if v >= 0 else '#E74C3C' for v in df_plot["MACD_Hist"]]
                    fig.add_trace(go.Bar(x=df_plot.index, y=df_plot["MACD_Hist"], name="MACD", marker_color=colors, showlegend=False), row=2, col=1)

                if "换手率" in df_plot.columns:
                    fig.add_trace(go.Area(x=df_plot.index, y=df_plot["换手率"], name="换手率", line=dict(color="#16A085", width=1), fill='tozeroy'), row=3, col=1)
            
            else:
                # 估值图
                fig = make_subplots(specs=[[{"secondary_y": True}]])
                fig.add_trace(go.Scatter(x=df_plot.index, y=df_plot["PE_正数等权"], name="PE(等权)", line=dict(color="red", width=2)), secondary_y=False)
                fig.add_trace(go.Scatter(x=df_plot.index, y=df_plot["PE_中位数"], name="PE(中位)", line=dict(color="orange", width=1.5)), secondary_y=False)
                
                window_5y = 250 * 5 if period == "日线" else 52 * 5
                window_10y = 250 * 10 if period == "日线" else 52 * 10
                
                df_plot['MA5_PE'] = df_plot['PE_正数等权'].rolling(window=window_5y, min_periods=1).mean()
                df_plot['MA10_PE'] = df_plot['PE_正数等权'].rolling(window=window_10y, min_periods=1).mean()
                
                fig.add_trace(go.Scatter(x=df_plot.index, y=df_plot["MA5_PE"], name="5年均线", line=dict(color="#7F8C8D", width=1.5)), secondary_y=False)
                fig.add_trace(go.Scatter(x=df_plot.index, y=df_plot["MA10_PE"], name="10年均线", line=dict(color="#2C3E50", width=1.5)), secondary_y=False)
                
                fig.add_trace(go.Scatter(x=df_plot.index, y=df_plot["指数点位"], name="指数点位", line=dict(color="#34495E", width=1.5), opacity=0.3), secondary_y=True)
                fig.update_yaxes(title_text="PE 估值", secondary_y=False)
                fig.update_yaxes(title_text="指数点位", secondary_y=True, showgrid=False)

            # ✅ 交易点位渲染 (超级增强匹配)
            all_trades_df = pd.DataFrame()
            trade_sources = []
            
            if not st.session_state['uploaded_trades'].empty:
                trade_sources.append(st.session_state['uploaded_trades'])
            
            saved_recs = load_trade_records()
            if saved_recs:
                trade_sources.append(pd.DataFrame(saved_recs))
            
            if trade_sources:
                try:
                    all_trades_df = pd.concat(trade_sources, ignore_index=True)
                    plot_df = all_trades_df.copy()
                    
                    plot_df.columns = [str(c).strip() for c in plot_df.columns]
                    rmap = {}
                    for c in plot_df.columns:
                        if "指数" in c: rmap[c]="指数"
                        if "操作" in c: rmap[c]="操作类型"
                        if "日期" in c: rmap[c]="日期"
                    plot_df = plot_df.rename(columns=rmap)
                    if "指数" in plot_df.columns: 
                        plot_df["指数"] = plot_df["指数"].astype(str).str.strip().replace("中证50","中证500")
                    
                    if {'日期','操作类型','指数'}.issubset(plot_df.columns):
                        plot_df['日期'] = pd.to_datetime(plot_df['日期'], errors='coerce')
                        
                        sel_name_clean = sel_name.replace("指数", "").strip()
                        plot_df['指数_clean'] = plot_df['指数'].astype(str).str.replace("指数", "").str.strip()
                        
                        # 模糊匹配
                        def is_match(row_idx):
                            return sel_name_clean in row_idx or row_idx in sel_name_clean
                        
                        ct = plot_df[plot_df['指数_clean'].apply(is_match)]
                        
                        if not ct.empty:
                            st.caption(f"📊 图中已标记 {len(ct)} 条交易")
                        
                        buys = ct[ct['操作类型'].astype(str).str.contains('买')]
                        sells = ct[ct['操作类型'].astype(str).str.contains('卖')]
                        
                        def get_y(dates, df_p):
                            ys = []
                            for d in dates:
                                try:
                                    idx = df_p.index.get_indexer([d], method='nearest')[0]
                                    ys.append(df_p.iloc[idx]['指数点位'])
                                except: ys.append(None)
                            return ys

                        is_sec = True if "估值" in view_mode else False
                        tar_row = 1
                        
                        if not buys.empty:
                            fig.add_trace(go.Scatter(x=buys['日期'], y=get_y(buys['日期'], df_plot), mode='markers', name='买入', marker=dict(symbol='triangle-up', size=12, color='red', line=dict(width=1, color='black'))), row=tar_row, col=1, secondary_y=is_sec)
                        if not sells.empty:
                            fig.add_trace(go.Scatter(x=sells['日期'], y=get_y(sells['日期'], df_plot), mode='markers', name='卖出', marker=dict(symbol='triangle-down', size=12, color='green', line=dict(width=1, color='black'))), row=tar_row, col=1, secondary_y=is_sec)
                except Exception as e:
                    pass

            fig.update_layout(height=600 if "估值" in view_mode else 700, hovermode="x unified", xaxis_rangeslider_visible=False)
            st.plotly_chart(fig, use_container_width=True)
            
            if not all_trades_df.empty:
                st.markdown("---")
                st.subheader("📋 完整交易账本")
                st.dataframe(all_trades_df, use_container_width=True)

if __name__ == "__main__":
    main()