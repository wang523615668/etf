# dashboard.py (V21.1 - 修正语法错误，完善交易管理)

import streamlit as st
import pandas as pd
import numpy as np 
import json
import os
from datetime import datetime, timedelta
import time
import glob 

# ================= 配置区域 (V21.1) =================

# 完整的指数列表
TARGETS = {
    "大盘.csv": "大盘指数",
    "沪深300.csv": "沪深300指数",
    "中证500.csv": "中证500指数",
    
    # 其他指数
    "全指医药.csv": "全指医药",
    "上证50.csv": "上证50",
    "创业板指.csv": "创业板指", 
    "养老产业.csv": "养老产业",
    "中证红利.csv": "中证红利",
    "中证环保.csv": "中证环保",
    "中证传媒.csv": "中证传媒",
    "全指金融.csv": "全指金融",
    "证券公司.csv": "证券公司",
    "全指消费.csv": "全指消费",
    "全指信息.csv": "全指信息",
    "中证医疗.csv": "中证医疗",
    "中证白酒.csv": "中证白酒",
}

# 限制详情和图表显示的最初三个核心指数 (在 V21.1 中主要用于主页数据展示)
INITIAL_TARGETS = {
    "大盘.csv": "大盘指数",
    "沪深300.csv": "沪深300指数",
    "中证500.csv": "中证500指数",
}

DATA_DIR = "index_data"
STATE_FILE = "portfolio_status.json" 

MAX_UNITS = 10          
STEP_PERCENT = 0.06     
MIN_INTERVAL_DAYS = 30 
VOLATILITY_OVERRIDE_PCT = 0.12 

# ================= 核心功能函数 =================

def load_state():
    """加载本地持仓状态"""
    if os.path.exists(STATE_FILE):
        try:
            state = json.load(open(STATE_FILE, 'r', encoding='utf-8'))
            for code in TARGETS.keys():
                if code not in state:
                     state[code] = {"holdings": 0, "history": []}
                elif "history" not in state[code]:
                     state[code]["history"] = []
            return state
        except json.JSONDecodeError:
            print("警告: 状态文件损坏，已重置。")
            return {code: {"holdings": 0, "history": []} for code in TARGETS.keys()}
    return {code: {"holdings": 0, "history": []} for code in TARGETS.keys()}

def save_state(state):
    """保存本地持仓状态"""
    # 每次保存前，重新计算 holdings，确保其与 history 保持一致
    recalculate_holdings(state)
    with open(STATE_FILE, 'w', encoding='utf-8') as f:
        json.dump(state, f, ensure_ascii=False, indent=4)

def recalculate_holdings(state):
    """根据交易历史重新计算当前持仓份数"""
    for code, data in state.items():
        if 'history' in data:
            total_units = 0
            for transaction in data['history']:
                unit = transaction.get('unit', 1) 
                if transaction.get('type') == '买入':
                    total_units += unit
                elif transaction.get('type') == '卖出':
                    total_units -= unit
            # 确保持仓份数不低于零
            state[code]['holdings'] = max(0, total_units)
    return state

def find_pe_by_date(df, target_date_str):
    """根据日期查找对应的 PE 值和收盘点位。"""
    try:
        target_date = pd.to_datetime(target_date_str)
        date_series = pd.to_datetime(df['Date'], errors='coerce') 
        row = df[date_series.dt.normalize() == target_date.normalize()]
        if not row.empty:
            close_price_col = '收盘' if '收盘' in df.columns else 'Close' 
            return row.iloc[0]['pe'], row.iloc[0][close_price_col]
        return np.nan, np.nan
    except Exception as e:
        return np.nan, np.nan

def find_latest_data_file(prefix):
    """查找匹配前缀的最新数据文件，并返回文件路径和修改时间 (支持模糊匹配)"""
    search_pattern = os.path.join(DATA_DIR, f"{prefix}_*.csv")
    matching_files = glob.glob(search_pattern)
    
    actual_file_path = None
    file_source_name = None
    last_modified_time = None
    
    if matching_files:
        actual_file_path = max(matching_files, key=os.path.getmtime)
        file_source_name = os.path.basename(actual_file_path)
        last_modified_time = datetime.fromtimestamp(os.path.getmtime(actual_file_path)).strftime('%Y-%m-%d %H:%M:%S')
    else:
        # 查找固定文件名作为备份
        fixed_path = os.path.join(DATA_DIR, f"{prefix}.csv")
        if os.path.exists(fixed_path):
            actual_file_path = fixed_path
            file_source_name = f"{prefix}.csv"
            last_modified_time = datetime.fromtimestamp(os.path.getmtime(fixed_path)).strftime('%Y-%m-%d %H:%M:%S')
        
    return actual_file_path, file_source_name, last_modified_time


@st.cache_data(ttl=3600)
def get_metrics_from_csv(file_path):
    """从本地 CSV 文件读取 PE 数据并计算指标。"""
    if not os.path.exists(file_path): return None
    try:
        df = pd.read_csv(file_path, encoding='utf-8', sep=',')
        if len(df) == 0: return None
        df = df.rename(columns={'PE-TTM正数等权': 'pe', '日期': 'Date', 'PE-TTM 分位点': 'pe_percentile', '收盘点位': 'Close', '收盘': 'Close'})
        for col in ['pe', 'pe_percentile', 'Close']:
             if col in df.columns:
                df[col] = df[col].astype(str).str.replace(r'[^\d.]', '', regex=True)
                df[col] = pd.to_numeric(df[col], errors='coerce') 
        df['Date'] = pd.to_datetime(df['Date'], errors='coerce')
        df = df[['Date', 'pe', 'pe_percentile', 'Close']].dropna(subset=['pe', 'Date', 'pe_percentile', 'Close'])
        df = df.sort_values('Date', ascending=True).reset_index(drop=True)
        if df.empty: return None
        df = df.set_index('Date')
        WINDOW_3Y = '1095D'; WINDOW_5Y = '1825D'; 
        df['avg_3yr_roll'] = df['pe'].rolling(window=WINDOW_3Y, min_periods=1, closed='left').mean()
        df['avg_5yr_roll'] = df['pe'].rolling(window=WINDOW_5Y, min_periods=1, closed='left').mean()
        df['benchmark_roll'] = df['avg_3yr_roll'] 
        df['deviation_pct'] = (df['pe'] - df['benchmark_roll']) / df['benchmark_roll'] * 100
        
        max_dev = df['deviation_pct'].max(); min_dev = df['deviation_pct'].min()
        
        if not np.isnan(max_dev): max_dev_date = df[df['deviation_pct'] == max_dev].iloc[-1].name.strftime('%Y-%m-%d')
        else: max_dev_date = 'N/A'
        if not np.isnan(min_dev): min_dev_date = df[df['deviation_pct'] == min_dev].iloc[-1].name.strftime('%Y-%m-%d')
        else: min_dev_date = 'N/A'
        
        avg_3yr = df['avg_3yr_roll'].iloc[-1]; avg_5yr = df['avg_5yr_roll'].iloc[-1]; avg_10yr = np.nan 
        df = df.reset_index().rename(columns={'index': 'Date'}); df['Date'] = df['Date'].dt.strftime('%Y-%m-%d')
        current_pe = df.iloc[-1]['pe']; current_percentile = df.iloc[-1]['pe_percentile']
        
        return (current_pe, current_percentile, avg_3yr, avg_5yr, avg_10yr, 
                df, max_dev, min_dev, max_dev_date, min_dev_date)
        
    except Exception as e:
        st.error(f"[{file_path}] 读取或处理数据失败: {e}")
        return None

def calculate_portfolio_metrics(s, current_close_index):
    """计算平均成本和浮动盈亏 (使用 ETF 实际价格估算)"""
    buy_records = [t for t in s['history'] if t['type'] == '买入' and 'price' in t and t['price'] is not None]
    
    if not buy_records:
        return np.nan, np.nan 

    total_cost = sum(t['price'] * t['unit'] for t in buy_records)
    total_units_bought = sum(t['unit'] for t in buy_records)
    
    avg_cost = total_cost / total_units_bought if total_units_bought > 0 else np.nan
    
    # 如果没有买入或当前持仓为0，盈亏无法计算
    if s['holdings'] == 0:
        return avg_cost, np.nan
    if np.isnan(avg_cost):
        return np.nan, np.nan
    
    # 找到最近一次买入的指数点位 (用于估算当前 ETF 价格)
    last_buy_index_close = next((t['close'] for t in reversed(s['history']) if t.get('type') == '买入' and t.get('close') is not None), np.nan)
    
    if not np.isnan(last_buy_index_close) and last_buy_index_close > 0:
        # 核心假设：ETF价格波动与指数点位波动一致，用指数点位比例估算当前 ETF 价格
        estimated_current_etf_price = avg_cost * (current_close_index / last_buy_index_close)
        floating_pl_pct = (estimated_current_etf_price / avg_cost) - 1
    else:
        floating_pl_pct = np.nan 
        
    return avg_cost, floating_pl_pct

def get_full_index_metrics(index_key, state, full_data_frames):
    """
    获取单个指数的完整指标、持仓和盈亏信息，用于子页面调用。
    
    返回: dict (包含 current_pe, current_close, holdings, avg_cost, pl_pct, df_full, history)
    """
    
    result = {
        "current_pe": np.nan, "current_close": np.nan, "holdings": 0, 
        "avg_cost": np.nan, "pl_pct": np.nan, "df_full": None, 
        "history": state.get(index_key, {}).get("history", [])
    }
    
    df_full = full_data_frames.get(index_key)
    # 确保持仓是最新的
    s = state.get(index_key, {})
    result["holdings"] = s.get("holdings", 0)
    
    # 如果缓存中没有数据，尝试加载
    if df_full is None:
        prefix = index_key.split('.')[0]
        actual_file_path, _, _ = find_latest_data_file(prefix)
        metrics_result = get_metrics_from_csv(actual_file_path)
        if metrics_result:
            df_full = metrics_result[5]
            result["current_pe"] = metrics_result[0]
            result["current_close"] = df_full.iloc[-1]['Close']
            
    if df_full is not None and not df_full.empty:
        result["df_full"] = df_full
        result["current_pe"] = df_full.iloc[-1]['pe']
        result["current_close"] = df_full.iloc[-1]['Close']
        
        avg_cost, pl_pct = calculate_portfolio_metrics(s, result["current_close"])
        result["avg_cost"] = avg_cost
        result["pl_pct"] = pl_pct
        
    return result

# ================= 颜色高亮函数 =================

def highlight_percentile(val):
    """根据估值百分位返回背景颜色样式"""
    try:
        if isinstance(val, str) and val.endswith('%'):
            pct = float(val.strip('%'))
        else: return '' 
            
        if pct < 20: return 'background-color: #d4edda; color: #155724; font-weight: bold' 
        elif 20 <= pct <= 50: return 'background-color: #fff3cd; color: #856404;' 
        elif 50 < pct <= 80: return 'background-color: #f8d7da; color: #721c24;' 
        elif pct > 80: return 'background-color: #dc3545; color: white; font-weight: bold' 
        else: return ''
    except: return ''

def highlight_signal(val):
    """根据建议信号返回背景颜色样式"""
    if '买入' in str(val):
        return f'background-color: #d4edda; color: #155724; font-weight: bold' 
    elif '卖出' in str(val):
        return f'background-color: #f8d7da; color: #721c24; font-weight: bold'
    elif '数据积累中' in str(val):
         return f'background-color: #fffac0; color: #b58d09; font-weight: bold'
    elif '跌幅不足 6%' in str(val):
         return 'background-color: #e0f7fa; color: #00796b; font-weight: bold' 
    elif '30天/±12%限制' in str(val): 
         return 'background-color: #e9ecef; color: #495057; font-weight: bold'
    else:
        return 'background-color: #f0f0f0; color: black;'

def highlight_pl(val):
    """根据浮动盈亏返回背景颜色样式"""
    try:
        if isinstance(val, str) and val.endswith('%'):
            pct = float(val.strip('%'))
        else: return '' 
            
        if pct > 0: return 'color: #155724; font-weight: bold' # 绿色字体
        elif pct < 0: return 'color: #721c24; font-weight: bold' # 红色字体
        else: return ''
    except: return ''

# ================= 页面布局（主体逻辑） =================

st.set_page_config(page_title="指数定投看板", layout="wide", page_icon="📈")

# --- 页面头部美化 (添加数据更新时间) ---
with st.container(border=True):
    st.markdown("## 📊 智能定投看板：估值总览与策略建议 (V21.1 - 交易管理)")
    st.markdown(f"**策略限制**: 每次操作间隔需大于 {MIN_INTERVAL_DAYS} 天，除非 PE 波动幅度大于 {VOLATILITY_OVERRIDE_PCT*100:.0f}%。")

# --- 侧边栏和数据新鲜度检查 ---
st.sidebar.header("🕹️ 操作面板")
st.sidebar.info(f"数据目录: **{DATA_DIR}/**")

# 查找最新的数据文件，获取更新时间
latest_modified_time = None
for prefix in [f.split('.')[0] for f in TARGETS.keys()]:
    _, _, mod_time = find_latest_data_file(prefix)
    if mod_time:
        if latest_modified_time is None or mod_time > latest_modified_time:
            latest_modified_time = mod_time

if latest_modified_time:
    st.sidebar.markdown(f"**最后数据更新时间：** `{latest_modified_time}`")
else:
    st.sidebar.warning("⚠️ 找不到数据文件，请检查 index_data 文件夹。")

# 加载状态 (重要: 运行时会重新计算 holdings)
state = load_state()
state = recalculate_holdings(state)
# 首次运行或 state 变更后保存，确保 holdings 正确
# save_state(state) # 避免在 rerurn 之前重复保存

# 主数据表格构建
table_data = []
decision_logs = {} 

progress_bar = st.progress(0, text="计算中...")
total_targets = len(TARGETS)
full_data_frames = {} 

# --- 大盘整体仓位指标计算 ---
overall_position_pct = 0
overall_pe_percentile = np.nan

if "大盘.csv" in TARGETS:
    prefix = "大盘"
    actual_file_path, file_source_name, _ = find_latest_data_file(prefix)
    if actual_file_path:
        metrics_result_overall = get_metrics_from_csv(actual_file_path)
        if metrics_result_overall:
            _, overall_pe_percentile, _, _, _, _, _, _, _, _ = metrics_result_overall
            if not np.isnan(overall_pe_percentile):
                overall_position_pct = (1 - overall_pe_percentile) * 100
    
# --- 数据加载、自动回填和指标计算 ---
updated_records_count = 0 

for i, (fixed_filename_key, name) in enumerate(TARGETS.items()): 
    
    prefix = fixed_filename_key.split('.')[0]
    progress_bar.progress((i + 1) / total_targets, text=f"正在处理 {name} ({i+1}/{total_targets}) - 匹配文件...")
    
    actual_file_path, file_source_name, _ = find_latest_data_file(prefix)
        
    if not actual_file_path:
        continue

    metrics_result = get_metrics_from_csv(actual_file_path) 
    code = fixed_filename_key
    s = state[code]
    current_holdings = s["holdings"]
    days_since_last_op_display = '—'
    avg_cost_display = '—'
    pl_pct_display = '—'

    current_decision_log = [] 

    if metrics_result:
        (curr_pe, curr_percentile, avg3, avg_5yr, avg_10yr, df_full, 
         max_dev, min_dev, max_dev_date, min_dev_date) = metrics_result
        
        full_data_frames[fixed_filename_key] = df_full 

        # --- 自动回填缺失数据 ---
        for trade in s['history']:
            if trade['pe'] is None or trade['close'] is None:
                new_pe, new_close = find_pe_by_date(df_full, trade['date'])
                if not np.isnan(new_pe) and not np.isnan(new_close):
                    trade['pe'] = round(new_pe, 2)
                    trade['close'] = round(new_close, 2)
                    updated_records_count += 1
        
        # --- P&L 计算 ---
        current_close_index = df_full.iloc[-1]['Close']
        avg_cost, pl_pct = calculate_portfolio_metrics(s, current_close_index)

        if not np.isnan(avg_cost):
            avg_cost_display = f"{avg_cost:.4f}"
        if not np.isnan(pl_pct):
            pl_pct_display = f"{pl_pct * 100:.2f}%"

        # --- 阶梯买入/时间限制判断 ---
        last_op = s["history"][-1] if s["history"] else None
        time_limit_suppression = False
        
        if last_op and 'pe' in last_op and last_op['pe'] is not None and not np.isnan(last_op['pe']):
            last_op_date_str = last_op.get("date", datetime.now().strftime("%Y-%m-%d"))
            last_op_date = datetime.strptime(last_op_date_str, "%Y-%m-%d").date()
            days_since_last_op = (datetime.now().date() - last_op_date).days
            days_since_last_op_display = str(days_since_last_op)
            
            current_decision_log.append(f"上次操作距今: {days_since_last_op} 天 (要求 ≥ {MIN_INTERVAL_DAYS} 天)")
            
            if days_since_last_op < MIN_INTERVAL_DAYS:
                last_op_pe = last_op['pe']
                pe_change_pct = (curr_pe - last_op_pe) / last_op_pe
                current_decision_log.append(f"上次操作PE: {last_op_pe:.2f}, 当前PE: {curr_pe:.2f}, 变动: {pe_change_pct*100:.1f}% (要求 ±{VOLATILITY_OVERRIDE_PCT*100:.0f}% 覆盖)")
                if abs(pe_change_pct) < VOLATILITY_OVERRIDE_PCT:
                    time_limit_suppression = True
                    current_decision_log.append("结果: 时间/波动率限制生效，抑制操作。")
                else:
                    current_decision_log.append("结果: 波动率达到覆盖条件，继续评估。")
            else:
                current_decision_log.append("结果: 已超过最小时间间隔，继续评估。")
        else:
             current_decision_log.append("无上次操作记录，不检查时间/波动率限制。")
        
        # --- 查找上次买入的PE (用于6%阶梯买入检查) ---
        last_buy_pe = None
        for trade in reversed(s["history"]):
            if trade['type'] == '买入' and trade['pe'] is not None and not np.isnan(trade['pe']):
                last_buy_pe = trade['pe']
                break
        
        last_op_hist = s["history"][-1] if s["history"] else {"date": "1900-01-01", "pe": 0, "close": 0}
        last_date = last_op_hist.get("date", "1900-01-01")
        last_pe = last_op_hist.get("pe") 
        if last_pe is None: last_pe = np.nan

        benchmark_pe = avg3 if not np.isnan(avg3) else 0 
        diff_pct = (curr_pe - benchmark_pe) / benchmark_pe * 100 if benchmark_pe > 0 else np.nan
        signal = "观望"
        
        # ==================== 信号判断逻辑 (含决策日志) ====================
        current_decision_log.append("--- 策略评估 ---")

        if benchmark_pe == 0 or np.isnan(benchmark_pe):
            signal = "⚠️ 数据积累中 (不满 3 年)"
            current_decision_log.append(f"条件: 3年均值 PE ({benchmark_pe:.2f}) 不足，无法评估。")
        
        elif time_limit_suppression:
            signal = f"⏸️ 观望 ({MIN_INTERVAL_DAYS}天/±{VOLATILITY_OVERRIDE_PCT*100:.0f}%限制)" 
            current_decision_log.append("条件: 被时间/波动率限制抑制。")

        else:
            current_decision_log.append(f"当前PE: {curr_pe:.2f}, PE分位点: {curr_percentile*100:.1f}%, 3年均值PE: {avg3:.2f}")

            buy_condition_1 = curr_percentile < 0.20 
            buy_condition_2 = (not np.isnan(avg3) and curr_pe < avg3) and (not np.isnan(avg_5yr) and curr_pe < avg_5yr) 
            
            sell_condition_1 = curr_percentile > 0.75 
            sell_condition_2 = diff_pct > 30 
            
            if sell_condition_1 or sell_condition_2:
                current_decision_log.append(f"条件: 卖出条件满足 (分位点 > 75% [{curr_percentile*100:.1f}%] 或偏离度 > 30% [{diff_pct:.1f}%])。")
                if current_holdings > 0: 
                    signal = "🔴 建议卖出"
                    current_decision_log.append("结果: 建议卖出。")
                else: 
                    signal = "🔴 建议卖出 (无持仓)。"
            
            elif buy_condition_1 or buy_condition_2:
                current_decision_log.append(f"条件: 买入条件满足 (分位点 < 20% [{curr_percentile*100:.1f}%] 或 PE < 3/5年均值)。")
                
                suppress_by_step = False
                if current_holdings > 0 and last_buy_pe is not None:
                    required_entry_pe = last_buy_pe * (1 - STEP_PERCENT)
                    current_decision_log.append(f"阶梯买入检查: 上次买入PE {last_buy_pe:.2f}, 下次买入PE阈值 {required_entry_pe:.2f} (要求跌幅 ≥ {STEP_PERCENT*100:.0f}%)。")
                    if curr_pe > required_entry_pe:
                        suppress_by_step = True
                        current_decision_log.append("结果: 跌幅不足 6%，抑制买入。")
                else:
                    current_decision_log.append(f"阶梯买入检查: 无持仓或无上次买入PE，不检查跌幅限制。")
                        
                if suppress_by_step:
                    signal = "⏸️ 观望 (跌幅不足 6%)"
                elif current_holdings < MAX_UNITS:
                    signal = "🟢 建议买入"
                    current_decision_log.append("结果: 建议买入。")
                else:
                    signal = "🟢 建议买入 (已满仓)"
                    current_decision_log.append("结果: 建议买入 (已满仓)。")
            else:
                current_decision_log.append("条件: 无明确买入/卖出信号。")
            
        decision_logs[code] = current_decision_log 

        table_data.append({
            "指数名称": name,
            "当前PE": f"{curr_pe:.2f}", 
            "PE分位点": f"{curr_percentile * 100:.1f}%", 
            "偏离度(3年%)": f"{diff_pct:.1f}%" if not np.isnan(diff_pct) else '—', 
            "建议信号": signal,
            "上次操作距今(天)": days_since_last_op_display,
            "平均成本(ETF)": avg_cost_display,
            "浮动盈亏(%)": pl_pct_display,
            "当前持仓(份)": current_holdings,
            "上次操作日期": last_date, 
            "上次操作PE": f"{last_pe:.2f}" if not np.isnan(last_pe) else '—', 
        })
    else:
        decision_logs[code] = ["数据处理失败或文件缺失，无法评估策略。"]
        table_data.append({
            "指数名称": name, 
            "建议信号": "⚠️ 数据处理失败/文件缺失",
            "PE分位点": "—", "偏离度(3年%)": "—", "当前PE": "—", 
            "上次操作距今(天)": '—',
            "平均成本(ETF)": '—', "浮动盈亏(%)": '—',
            "当前持仓(份)": s["holdings"], "上次操作日期": last_date, "上次操作PE": "—"
        })

progress_bar.empty()

# --- 检查是否需要保存状态和重新运行 ---
if updated_records_count > 0:
    save_state(state)
    st.success(f"✅ 已自动补录 {updated_records_count} 条交易记录的 PE/点位数据!")
    st.cache_data.clear() 
    time.sleep(1)
    st.rerun()

# --- 核心指标显示区 (顶部增加整体仓位指标) ---
st.subheader("核心指标")
col_overall_pos, col_curr_pe, col_percentile, col_deviation = st.columns([1,1,1,1]) 

with col_overall_pos.container(border=True):
    st.markdown("### 🌎 整体仓位指标")
    if not np.isnan(overall_pe_percentile):
        overall_position_str = f"{overall_position_pct:.1f}%"
        st.metric(label="建议整体仓位 (1-大盘分位)", value=overall_position_str)
        if overall_position_pct > 75:
            st.success("市场整体低估，可积极布局。")
        elif overall_position_pct < 25:
            st.error("市场整体高估，注意风险。")
        else:
            st.info("市场估值适中。")
    else:
        st.info("大盘数据缺失，无法计算。")

with col_curr_pe.container(border=True):
    st.markdown(f"### 🎯 当前指数总数")
    st.metric(label="监控中指数数量", value=len(TARGETS))
    st.markdown("数据驱动您的分散投资决策。")

with col_percentile.container(border=True):
    st.markdown("### 📈 PE分位点")
    st.info("绿色: <20% (低估) | 红色: >80% (高估)")
    st.markdown("评估当前估值在历史上的相对位置。")

with col_deviation.container(border=True):
    st.markdown("### 💡 建议信号")
    st.success("🟢: 建议买入")
    st.error("🔴: 建议卖出")
    st.markdown("基于多重指标(3/5年均值, 分位点)生成的策略建议。")

st.markdown("---")

st.subheader("📋 指数估值与策略总览")

df_display = pd.DataFrame(table_data)

st.dataframe(
    df_display.style
        .applymap(highlight_signal, subset=['建议信号'])
        .applymap(highlight_percentile, subset=['PE分位点'])
        .applymap(highlight_pl, subset=['浮动盈亏(%)']),
    use_container_width=True,
    height=500
)

# --- 详细的决策依据显示 (扩展到所有指数) ---
st.markdown("---")
st.subheader("🔍 详细决策依据 (所有指数)")
for code, name in TARGETS.items(): 
    with st.expander(f"**{name}** 建议信号决策日志"):
        if code in decision_logs and decision_logs[code]:
            for log_entry in decision_logs[code]:
                st.markdown(f"- {log_entry}")
        else:
            st.info("无决策日志信息。")

# --- 交易登记逻辑 (新增交易管理) ---
st.markdown("---")
st.header("🛒 交易登记与管理")

tab_record, tab_manage = st.tabs(["📝 登记新交易", "🗑️ 管理/修改交易记录"])

# ======================= Tab 1: 登记新交易 =======================
with tab_record:
    st.markdown("登记新的买入或卖出记录。")
    with st.container(border=True):
        col1, col2, col3, col4, col5 = st.columns([2, 1, 2, 2, 2])

        name_options = list(TARGETS.values())

        with col1:
            selected_name_r = st.selectbox("选择指数", name_options, key="select_record_index")
            selected_file_r = [f for f, n in TARGETS.items() if n == selected_name_r][0]

        with col2:
            action_r = st.selectbox("操作类型", ["买入", "卖出"], key="select_action")
            
        with col3:
            trade_date_r = st.date_input("成交日期", value=datetime.now().date(), max_value=datetime.now().date(), key="input_date")
            trade_date_str_r = trade_date_r.strftime("%Y-%m-%d")

        with col4:
            price_label_r = "ETF 实际成交价格"
            
            # 尝试获取最近的交易价格作为默认值
            last_buy_price_r = next((t['price'] for t in reversed(state[selected_file_r]['history']) if t.get('type') == '买入' and t.get('price') is not None), 1.0000)
            
            trade_price_r = st.number_input(price_label_r, min_value=0.0001, format="%.4f", value=last_buy_price_r, step=0.0001, key="input_price")

        with col5:
            st.markdown("##### ") 
            st.markdown("##### ") 
            if st.button("提交新记录", type="primary", use_container_width=True):
                s = state[selected_file_r] 
                df_selected_r = full_data_frames.get(selected_file_r)
                
                if df_selected_r is None:
                    st.error(f"⚠️ 无法提交记录：数据文件 {selected_file_r} 读取失败。")
                    time.sleep(1); st.cache_data.clear(); st.rerun()

                trade_pe_r, trade_close_r = find_pe_by_date(df_selected_r, trade_date_str_r)
                
                saved_pe_r = round(trade_pe_r, 2) if not np.isnan(trade_pe_r) else None
                saved_close_r = round(trade_close_r, 2) if not np.isnan(trade_close_r) else None
                
                is_data_missing_r = saved_pe_r is None or saved_close_r is None
                
                pe_display_str_r = f"{saved_pe_r:.2f}" if not is_data_missing_r else 'N/A'
                    
                transaction_r = {
                    "date": trade_date_str_r,
                    "type": action_r,
                    "pe": saved_pe_r, 
                    "close": saved_close_r,
                    "price": trade_price_r, 
                    "unit": 1 # 默认每次交易一份
                }
                
                if action_r == "买入":
                    if s["holdings"] < MAX_UNITS:
                        s["history"].append(transaction_r) 
                        save_state(state)
                        st.success(f"已记录：{selected_name_r} 买入1份。PE: {pe_display_str_r}, ETF成交价: {trade_price_r:.4f}。当前持仓 {state[selected_file_r]['holdings']} 份。")
                    else:
                        st.info(f"已达到最大持仓份数 ({MAX_UNITS})，无法继续买入。")
                    
                elif action_r == "卖出":
                    if s["holdings"] > 0:
                        s["history"].append(transaction_r) 
                        save_state(state)
                        st.warning(f"已记录：{selected_name_r} 卖出1份。PE: {pe_display_str_r}, ETF成交价: {trade_price_r:.4f}。当前持仓 {state[selected_file_r]['holdings']} 份。")
                    else:
                        st.error("持仓为0，无法卖出。")
                        
                time.sleep(1)
                st.cache_data.clear() 
                st.rerun()

# ======================= Tab 2: 管理/修改交易记录 =======================
with tab_manage:
    st.markdown("⚠️ **危险操作！** 删除和修改记录将直接影响持仓和成本计算。")

    name_options_m = list(TARGETS.values())
    selected_name_m = st.selectbox("选择要管理记录的指数", name_options_m, key="select_manage_index")
    selected_file_m = [f for f, n in TARGETS.items() if n == selected_name_m][0]
    
    s_m = state[selected_file_m]
    
    if not s_m['history']:
        st.info("该指数尚无交易记录可供管理。")
    else:
        # 将历史记录转换为 DataFrame 以便展示索引
        history_df_m = pd.DataFrame(s_m['history'])
        history_df_m['index'] = history_df_m.index # 添加索引列用于识别记录
        
        # 简化 DataFrame 以供 Streamlit 展示
        df_display_m = history_df_m[['index', 'date', 'type', 'price', 'unit', 'pe', 'close']].copy()
        df_display_m = df_display_m.rename(columns={'index': '索引', 'date': '成交日期', 'type': '操作类型', 'price': 'ETF成交价', 'unit': '交易份数', 'pe': '成交PE(自动)', 'close': '成交点位(自动)'})
        
        # 格式化 PE/Close/Price，防止 NaN 显示问题
        for col in ['ETF成交价', '成交PE(自动)', '成交点位(自动)']:
             if col in df_display_m.columns:
                if col == 'ETF成交价':
                    df_display_m[col] = df_display_m[col].apply(lambda x: f"{x:.4f}" if pd.notna(x) and x is not None else 'N/A')
                else:
                    df_display_m[col] = df_display_m[col].apply(lambda x: f"{x:.2f}" if pd.notna(x) and x is not None else 'N/A')
        
        st.dataframe(df_display_m, use_container_width=True)

        # --- 删除操作 ---
        st.subheader("删除记录")
        col_del, col_button_del = st.columns([1, 1])
        with col_del:
            index_to_delete = st.number_input("输入要删除的记录行索引 (最左侧列)", min_value=0, max_value=len(history_df_m) - 1, step=1, key="delete_index")
        
        with col_button_del:
            st.markdown("##### ")
            if st.button(f"🔴 确认删除第 {index_to_delete} 行记录", key="confirm_delete_button"):
                # 确保索引有效
                if 0 <= index_to_delete < len(s_m['history']):
                    del s_m['history'][index_to_delete]
                    save_state(state)
                    st.success(f"✅ 记录 {index_to_delete} 已删除，持仓已重新计算。")
                    time.sleep(1)
                    st.cache_data.clear() 
                    st.rerun()
                else:
                    st.error("索引超出范围，请检查输入。")

        st.markdown("---")
        
        # --- 修改操作 (仅支持修改价格/日期/类型/份数) ---
        st.subheader("修改记录")
        
        df_selected_m = full_data_frames.get(selected_file_m)
        if df_selected_m is None:
            st.error("无法获取指数数据，无法进行修改。请确保数据文件存在。")
        else:
            col_mod_index, col_mod_type, col_mod_date, col_mod_price = st.columns(4)
            
            # 1. 选择要修改的索引
            with col_mod_index:
                index_to_modify = st.number_input("输入要修改的记录行索引", min_value=0, max_value=len(history_df_m) - 1, step=1, key="modify_index")
            
            # 确保索引有效
            if 0 <= index_to_modify < len(s_m['history']):
                record_to_modify = s_m['history'][index_to_modify]
                
                # 2. 修改操作类型
                with col_mod_type:
                    new_type = st.selectbox("新操作类型", ["买入", "卖出"], index=0 if record_to_modify.get('type') == '买入' else 1, key="modify_type")

                # 3. 修改成交日期
                with col_mod_date:
                    try:
                        current_date = datetime.strptime(record_to_modify.get('date'), "%Y-%m-%d").date()
                    except:
                         current_date = datetime.now().date()
                    new_date = st.date_input("新成交日期", value=current_date, max_value=datetime.now().date(), key="modify_date")
                    new_date_str = new_date.strftime("%Y-%m-%d")

                # 4. 修改 ETF 价格
                with col_mod_price:
                    new_price = st.number_input("新ETF成交价", min_value=0.0001, format="%.4f", value=record_to_modify.get('price', 1.0000), step=0.0001, key="modify_price")
                    
                # 5. 修改份数 (默认为 1)
                new_unit = st.number_input("新交易份数", min_value=1, value=record_to_modify.get('unit', 1), step=1, key="modify_unit")

                if st.button(f"🟡 确认修改第 {index_to_modify} 行记录", key="confirm_modify_button"):
                    
                    # 重新查找新的 PE/Close
                    trade_pe_mod, trade_close_mod = find_pe_by_date(df_selected_m, new_date_str)
                    saved_pe_mod = round(trade_pe_mod, 2) if not np.isnan(trade_pe_mod) else None
                    saved_close_mod = round(trade_close_mod, 2) if not np.isnan(trade_close_mod) else None

                    # 更新记录
                    s_m['history'][index_to_modify] = {
                        "date": new_date_str,
                        "type": new_type,
                        "pe": saved_pe_mod, 
                        "close": saved_close_mod,
                        "price": new_price, 
                        "unit": new_unit
                    }

                    save_state(state)
                    st.success(f"✅ 记录 {index_to_modify} 已更新并重新计算持仓。")
                    time.sleep(1)
                    st.cache_data.clear() 
                    st.rerun()
            else:
                st.error("索引超出范围，请检查输入。")
