# dashboard.py (V22.0 - 策略参数化、回填优化、成本精确化)

import streamlit as st
import pandas as pd
import numpy as np
import json
import os
from datetime import datetime, timedelta
import time
import glob

# ================= 配置区域 (V22.0) =================

# 完整的指数列表 (保留您 V21.1 提供的配置)
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

DATA_DIR = "index_data"
STATE_FILE = "portfolio_status.json"

# V23.2: 资金/份数固定金额配置
FIXED_AMOUNT_PER_PORTION = 300.0 # 每份固定金额# 初始默认值，用于首次加载 Session State
DEFAULT_STRATEGY_PARAMS = {
    "MAX_UNITS": 150,                 # 最大买入份数 (现在是总份数 150 份)
    "STEP_PERCENT": 0.06,            # 阶梯买入跌幅 (6%)
    "MIN_INTERVAL_DAYS": 30,         # 最小操作间隔天数 (30天)
    "VOLATILITY_OVERRIDE_PCT": 0.12, # 波动率限制覆盖比例 (12%)
}
MAX_UNITS_DEFAULT = DEFAULT_STRATEGY_PARAMS["MAX_UNITS"]
MIN_INTERVAL_DAYS = DEFAULT_STRATEGY_PARAMS["MIN_INTERVAL_DAYS"]
VOLATILITY_OVERRIDE_PCT = DEFAULT_STRATEGY_PARAMS["VOLATILITY_OVERRIDE_PCT"]

# V23.3: 资金/份数固定金额配置
FIXED_AMOUNT_PER_PORTION = 300.0 # 每份固定金额


# ====================================================================
# 核心状态函数 (V23.3: 引入 portions 字段)
# ====================================================================

def initialize_session_state():
    """初始化 Streamlit Session State，包括策略参数。"""
    if 'strategy_params' not in st.session_state:
        st.session_state['strategy_params'] = DEFAULT_STRATEGY_PARAMS

def get_strategy_param(key):
    """获取当前策略参数值。"""
    initialize_session_state()
    return st.session_state['strategy_params'].get(key, DEFAULT_STRATEGY_PARAMS.get(key))

def load_state():
    """加载应用状态，健壮地处理文件不存在、文件为空或文件损坏的情况。"""
    
    # 假设 STATE_FILE 是全局定义的（如 "user_state.json"）
    # 假设 TARGETS 是全局定义的指数列表
    
    # 定义初始状态，用于文件不存在或损坏时重置
    initial_state = {
        code: {"holdings": 0.0, "total_cost": 0.0, "portions_held": 0.0, "history": []} 
        for code in TARGETS.keys()
    }

    if os.path.exists(STATE_FILE):
        
        # 🚨 关键修复：在读取 JSON 之前检查文件大小
        if os.path.getsize(STATE_FILE) == 0:
            st.warning("警告: 状态文件为空（0字节），已重置。")
            return initial_state
            
        try:
            # 优化：使用 with open 语句
            with open(STATE_FILE, 'r', encoding='utf-8') as f:
                state = json.load(f)
                
            # 确保所有指数都有完整的结构
            for code in TARGETS.keys():
                if code not in state:
                    state[code] = initial_state[code]
                else:
                    # 兼容性检查：确保所有关键字段都存在
                    if "total_cost" not in state[code]: state[code]["total_cost"] = 0.0 
                    if "holdings" not in state[code]: state[code]["holdings"] = 0.0
                    if "portions_held" not in state[code]: state[code]["portions_held"] = 0.0 
                    if "history" not in state[code]: state[code]["history"] = []
                    
                    # 确保 history 记录中包含 'portions' 和 'fund_name' 字段 (兼容旧数据)
                    for h in state[code]["history"]:
                        if "portions" not in h:
                            # 兼容旧记录的 portions 估算逻辑
                            if h.get('price') and h.get('unit'):
                                # 假设 FIXED_AMOUNT_PER_PORTION 在全局范围内可用
                                h['portions'] = round((h['price'] * h['unit']) / FIXED_AMOUNT_PER_PORTION, 0)
                            else:
                                h['portions'] = 0 # 无法估算
                        
                        if "fund_name" not in h:
                            h['fund_name'] = ""
                            
            # 确保在返回前，重新计算持仓和成本（重要）
            return recalculate_holdings_and_cost(state) 
            
        except json.JSONDecodeError as e:
            # 捕获 JSON 格式错误
            st.error(f"警告: 状态文件损坏 ({STATE_FILE})，已重置。错误: {e}")
            return initial_state
            
        except Exception as e:
            # 捕获其他如 AttributeError 等未知错误
            st.error(f"警告: 状态文件加载失败，已重置。错误: {e}")
            return initial_state
            
    # 文件不存在
    return initial_state


def save_state(state):
    """将当前状态保存到本地 JSON 文件。"""
    try:
        # V22.0: 在保存前，确保 history 中的 date 是字符串格式
        state_to_save = {}
        for k, data in state.items():
            data_to_save = data.copy()
            if 'history' in data_to_save:
                data_to_save['history'] = [
                    {**h, 'date': h['date'].strftime('%Y-%m-%d') if hasattr(h['date'], 'strftime') else h['date']}
                    for h in data_to_save['history']
                ]
            state_to_save[k] = data_to_save
            
        with open(STATE_FILE, 'w', encoding='utf-8') as f:
            json.dump(state_to_save, f, ensure_ascii=False, indent=4)
        return True
    except Exception as e:
        st.error(f"保存状态到 {STATE_FILE} 失败。错误: {e}")
        return False


def calculate_total_portions(history):
    """V23.3: 根据历史记录中新增的 'portions' 字段计算当前持有的总份数。"""
    total_portions = 0.0
    for transaction in history:
        # 兼容性说明: 交易记录必须包含 portions 字段
        portions = transaction.get('portions', 0.0) 
        
        if transaction.get('type') == '买入':
            total_portions += portions
        elif transaction.get('type') == '卖出':
            total_portions -= portions
    return max(0.0, total_portions)


def recalculate_holdings_and_cost(state):
    """V23.3: 遍历所有指数，重新计算并更新状态中的持仓、总成本和总份数。"""
    for code, data in state.items():
        if 'history' in data:
            # 1. 计算基金份额和总成本（使用旧的 calculate_index_cost）
            total_units, total_cost = calculate_index_cost(data['history'])
            
            # 2. 计算份数（使用新的 calculate_total_portions）
            total_portions = calculate_total_portions(data['history']) 
            
            state[code]['holdings'] = total_units # 仍是基金份额
            state[code]['total_cost'] = total_cost
            state[code]['portions_held'] = total_portions # V23.3 新增字段保存总份数
    return state


def calculate_index_cost(history):
    """
    根据历史记录计算当前持仓份额和总成本。
    逻辑更新：直接使用 'unit'(份额) 和 'price'(净值) 计算。
    Total Cost = Sum(Buy Price * Buy Unit) - Cost of Sold Units
    """
    total_units = 0.0
    total_cost = 0.0
    
    for transaction in history:
        # 获取份额，如果没有则默认为0
        unit = float(transaction.get('unit', 0.0))
        price = float(transaction.get('price', 0.0))
        
        # 兼容旧数据：如果旧数据只有 'portions' 没有 'unit'，在这里做一个临时转换(可选)
        # if unit == 0 and transaction.get('portions'):
        #     unit = transaction.get('portions') * 300 / price 
        
        if transaction.get('type') == '买入':
            cost_increase = price * unit
            total_cost += cost_increase
            total_units += unit
            
        elif transaction.get('type') == '卖出':
            if total_units > 0:
                # 卖出时，按平均成本减少总成本
                avg_cost_per_unit = total_cost / total_units
                cost_decrease = avg_cost_per_unit * unit
                
                total_cost -= cost_decrease
                total_units -= unit
                
                # 防止浮点数误差
                if total_units < 1e-6:
                    total_units = 0.0
                    total_cost = 0.0
            
    return max(0.0, total_units), max(0.0, total_cost)

# 同时更新 recalculate_holdings_and_cost 函数
def recalculate_holdings_and_cost(state):
    for code, data in state.items():
        if 'history' in data:
            total_units, total_cost = calculate_index_cost(data['history'])
            state[code]['holdings'] = total_units # 现在的 holdings 就是真实的基金份额
            state[code]['total_cost'] = total_cost
            # portions_held 字段不再需要用于核心计算，但可以保留为 0 防止报错
            state[code]['portions_held'] = 0 
    return state

# ================= 核心数据处理函数 (V22.0 优化) =================

# V22.0: 改进 find_pe_by_date，支持向前查找 (Forward Fill)
def find_pe_by_date(df, target_date_str):
    """根据日期查找对应的 PE 值和收盘点位。如果当天无数据，向前查找最近的交易日。"""
    try:
        target_date = pd.to_datetime(target_date_str)
        # 确保 df 索引是 datetime
        df_temp = df.copy()
        df_temp['Date'] = pd.to_datetime(df_temp['Date'], errors='coerce')
        df_temp = df_temp.set_index('Date').sort_index()
        
        # 尝试精确匹配当天数据
        if target_date in df_temp.index:
             row = df_temp.loc[target_date]
             return row['pe'], row['Close']
             
        # 如果当天没有数据，使用 reindex/ffill 查找最近的前一个交易日数据
        # 创建一个包含目标日期的临时索引
        temp_index = df_temp.index.union([target_date]).sort_values()
        df_reindexed = df_temp.reindex(temp_index)
        
        # 使用前一个有效值填充目标日期
        df_reindexed = df_reindexed.ffill()
        
        # 查找目标日期的 PE 和 Close
        if target_date in df_reindexed.index:
            row = df_reindexed.loc[target_date]
            # 确保这不是一个 NaN 填充的结果
            if pd.notna(row['pe']):
                return row['pe'], row['Close']

        return np.nan, np.nan
    except Exception as e:
        # st.error(f"查找 PE/Close 失败: {e}")
        return np.nan, np.nan


def find_latest_data_file(prefix):
    """查找匹配前缀的最新数据文件，并返回文件路径和修改时间 (支持模糊匹配)"""
    # ... (此函数保持不变，因为它在您的 V21.1 中已经工作正常) ...
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
 
    if not os.path.exists(file_path): return None
    try:
        df = pd.read_csv(file_path, encoding='utf-8', sep=',')
        if len(df) == 0: return None
        
        # V22.0: 兼容性调整，优先使用简短的列名
        df = df.rename(columns={'PE-TTM正数等权': 'pe', '日期': 'Date', 
                                'PE-TTM 分位点': 'pe_percentile', 
                                '收盘点位': 'Close', '收盘': 'Close', 
                                'Close': 'Close', 'Date': 'Date'})
        
        for col in ['pe', 'pe_percentile', 'Close']:
             if col in df.columns:
                 df[col] = df[col].astype(str).str.replace(r'[^\d.]', '', regex=True)
                 df[col] = pd.to_numeric(df[col], errors='coerce') 
        
     # 1. 必须确保 Date 是 datetime 类型并设为索引，才能使用基于时间的 rolling
        df['Date'] = pd.to_datetime(df['Date'], errors='coerce')  # <--- 这行是报错行
        df = df[['Date', 'pe', 'pe_percentile', 'Close']].dropna(subset=['pe', 'Date', 'pe_percentile', 'Close'])
        df = df.sort_values('Date', ascending=True).reset_index(drop=True)
    
        if df.empty: return None
    
    # === 关键修改：设置索引为日期，以便进行时间窗口计算 ===
        df = df.set_index('Date') 
    
    # 2. 定义时间窗口 (365天*N)
        WINDOW_3Y = '1095D'  # 365 * 3
        WINDOW_5Y = '1825D'  # 365 * 5
        WINDOW_10Y = '3650D' # 365 * 10
    
    # 3. 使用基于时间的 rolling (closed='left' 表示不包含当天)
        df['avg_3yr_roll'] = df['pe'].rolling(window=WINDOW_3Y, min_periods=1, closed='left').mean()
        df['avg_5yr_roll'] = df['pe'].rolling(window=WINDOW_5Y, min_periods=1, closed='left').mean()
        df['avg_10yr_roll'] = df['pe'].rolling(window=WINDOW_10Y, min_periods=1, closed='left').mean()
        # ==========================================
 # 4. === 核心修正：基于时间长度强制 NaN ===
        earliest_date = df.index[0]
        
        # 计算 3 年后的日期（即开始计算三年平均值的日期）
        START_DATE_3Y = earliest_date + pd.Timedelta(days=1095)
        # 强制将早于该日期的滚动平均值设为 NaN
        df.loc[df.index < START_DATE_3Y, 'avg_3yr_roll'] = np.nan
        
        # 5 年
        START_DATE_5Y = earliest_date + pd.Timedelta(days=1825)
        df.loc[df.index < START_DATE_5Y, 'avg_5yr_roll'] = np.nan
        
        # 10 年
        START_DATE_10Y = earliest_date + pd.Timedelta(days=3650)
        df.loc[df.index < START_DATE_10Y, 'avg_10yr_roll'] = np.nan
        # ==========================================
           
        df['benchmark_roll'] = df['avg_3yr_roll'] 
        df['deviation_pct'] = (df['pe'] - df['benchmark_roll']) / df['benchmark_roll'] * 100
        
        max_dev = df['deviation_pct'].max(); min_dev = df['deviation_pct'].min()
        
        if not np.isnan(max_dev): max_dev_date = df[df['deviation_pct'] == max_dev].iloc[-1].name.strftime('%Y-%m-%d')
        else: max_dev_date = 'N/A'
        if not np.isnan(min_dev): min_dev_date = df[df['deviation_pct'] == min_dev].iloc[-1].name.strftime('%Y-%m-%d')
        else: min_dev_date = 'N/A'
        
        # (可选) 更新单点均值变量，使其不为 NaN，虽然绘图主要用上面的 roll 数组
        avg_3yr = df['avg_3yr_roll'].iloc[-1]
        avg_5yr = df['avg_5yr_roll'].iloc[-1]
        avg_10yr = df['avg_10yr_roll'].iloc[-1] # 这里原来是 np.nan，现在可以取值了
        df = df.reset_index().rename(columns={'index': 'Date'}); df['Date'] = df['Date'].dt.strftime('%Y-%m-%d')
        current_pe = df.iloc[-1]['pe']; current_percentile = df.iloc[-1]['pe_percentile']

    # 计算最大/最小偏离度 (用于表格展示)
        max_dev = df['deviation_pct'].max()
        min_dev = df['deviation_pct'].min()
        
        return (current_pe, current_percentile, avg_3yr, avg_5yr, avg_10yr, 
                df, max_dev, min_dev, max_dev_date, min_dev_date)
        
    except Exception as e:
        st.error(f"[{file_path}] 读取或处理数据失败: {e}")
        return None

# V22.0: 重命名并改进盈亏计算，基于精确的总成本
def calculate_index_pl_metrics(s, current_close_index, df_full):
    """
    V22.0: 计算单个指数的平均成本和浮动盈亏。
    使用精确的 total_cost 和 holdings 计算平均成本。
    """
    total_units = s.get('holdings', 0.0)
    total_cost = s.get('total_cost', 0.0)

    if total_units == 0:
        return np.nan, np.nan, np.nan  # avg_cost, floating_pl_pct, total_market_value

    # 1. 计算平均成本
    avg_cost = total_cost / total_units

    # 2. 估算当前市场价值 (使用最新的 ETF 价格)
    
    # 查找最近一次操作的 ETF 成交价和对应的指数点位
    last_trade = next((t for t in reversed(s['history']) if t.get('price') is not None and t.get('close') is not None), None)

    if last_trade and last_trade['close'] > 0:
        last_trade_etf_price = last_trade['price']
        last_trade_index_close = last_trade['close']
        
        # 核心假设：ETF价格波动与指数点位波动一致
        estimated_current_etf_price = last_trade_etf_price * (current_close_index / last_trade_index_close)
        
        total_market_value = estimated_current_etf_price * total_units
        floating_pl_pct = (total_market_value / total_cost) - 1
        
        return avg_cost, floating_pl_pct, total_market_value
    else:
        # 如果没有有效的交易记录来建立估算基准，则无法计算盈亏
        return avg_cost, np.nan, np.nan

def get_full_index_metrics(index_key, state, full_data_frames):
    """
    V22.0: 获取单个指数的完整指标、持仓和盈亏信息，用于子页面调用。
    """
    
    # ... (此函数保持不变，因为它是 V21.1 中的调用接口，我们只改变其调用的子函数) ...
    result = {
        "current_pe": np.nan, "current_close": np.nan, "holdings": 0.0, 
        "avg_cost": np.nan, "pl_pct": np.nan, "df_full": None, 
        "history": state.get(index_key, {}).get("history", [])
    }
    
    df_full = full_data_frames.get(index_key)
    s = state.get(index_key, {})
    result["holdings"] = s.get("holdings", 0.0)
    
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
        
        # V22.0: 调用新的盈亏计算函数
        avg_cost, pl_pct, total_market_val = calculate_index_pl_metrics(s, current_close_index, df_full) # 注意：原函数第3个返回值是市值

        # === 新增：收集饼图数据 ===
        # 如果有持仓，则记录市值（优先）或成本
        if current_holdings > 0:
            # 如果 calculate_index_pl_metrics 返回了市值则用市值，否则用总成本
            value_for_pie = total_market_val if (total_market_val is not None and not np.isnan(total_market_val)) else current_total_cost
            pie_chart_data.append({
                "name": name,
                "value": value_for_pie
            })
        # ========================
        result["avg_cost"] = avg_cost
        result["pl_pct"] = pl_pct
        result["total_market_val"] = value_for_pie
    return result

# ================= 颜色高亮函数 =================

# ... (高亮函数保持不变) ...

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
    elif '跌幅不足' in str(val):
         return 'background-color: #e0f7fa; color: #00796b; font-weight: bold' 
    elif '限制' in str(val): 
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

# ================= 页面布局（主体逻辑） (V22.0 优化) =================
st.set_page_config(page_title="指数定投看板", layout="wide", page_icon="📈")

# --- 页面头部美化与CSS设置 ---
st.markdown("""
<style>
/* 强制缩小 st.metric 的数字字体 */
div[data-testid="stMetricValue"] > div {
    font-size: 16px !important; /* 原来可能是 24px 或 30px，改小 */
    font-weight: bold;
}
/* 缩小标题字体 */
div[data-testid="stMetricLabel"] label {
    font-size: 13px !important;
}
/* 调整 Metric 容器的紧凑度 */
div[data-testid="stMetric"] {
    background-color: #f9f9f9;
    padding: 5px 10px;
    border-radius: 5px;
}
</style>
""", unsafe_allow_html=True)

# ===========================================

# V22.0: 初始化 Session State
initialize_session_state()

# --- 页面头部美化 ---
with st.container(border=True):
    st.markdown("## 📊 智能定投看板：估值总览与策略建议 (V22.0 - 优化版)")
    
    # V22.0: 从 Session State 读取参数
    MIN_INTERVAL_DAYS = get_strategy_param("MIN_INTERVAL_DAYS")
    VOLATILITY_OVERRIDE_PCT = get_strategy_param("VOLATILITY_OVERRIDE_PCT")
    
    st.markdown(f"**策略限制**: 每次操作间隔需大于 **{MIN_INTERVAL_DAYS}** 天，除非 PE 波动幅度大于 **{VOLATILITY_OVERRIDE_PCT*100:.0f}%**。")

# --- 侧边栏和数据新鲜度检查 (V22.0 策略配置) ---
st.sidebar.header("🕹️ 策略配置 (V22.0)")

# V22.0: 策略参数化配置
with st.sidebar.expander("⚙️ 策略参数设置"):
    
    MAX_UNITS = st.number_input(
        "最大持仓份数 (MAX_UNITS):", 
        min_value=1, value=get_strategy_param("MAX_UNITS"), step=1, key='param_max_units'
    )
    STEP_PERCENT = st.number_input(
        "阶梯买入跌幅 (STEP_PERCENT, %):", 
        min_value=1.0, max_value=20.0, value=get_strategy_param("STEP_PERCENT")*100, step=0.5, format="%.1f"
    ) / 100
    MIN_INTERVAL_DAYS = st.number_input(
        "最小操作间隔 (天):", 
        min_value=1, value=get_strategy_param("MIN_INTERVAL_DAYS"), step=1, key='param_min_days'
    )
    VOLATILITY_OVERRIDE_PCT = st.number_input(
        "波动率覆盖比例 (%):", 
        min_value=1.0, max_value=50.0, value=get_strategy_param("VOLATILITY_OVERRIDE_PCT")*100, step=1.0, format="%.0f"
    ) / 100
    
    if st.button("保存策略参数并刷新", type="primary"):
        st.session_state['strategy_params'] = {
            "MAX_UNITS": MAX_UNITS,
            "STEP_PERCENT": STEP_PERCENT,
            "MIN_INTERVAL_DAYS": MIN_INTERVAL_DAYS,
            "VOLATILITY_OVERRIDE_PCT": VOLATILITY_OVERRIDE_PCT,
        }
        st.success("参数已更新！")
        st.cache_data.clear()
        st.rerun()

# V22.0: 读取最新的参数值
MAX_UNITS = get_strategy_param("MAX_UNITS")
STEP_PERCENT = get_strategy_param("STEP_PERCENT")
MIN_INTERVAL_DAYS = get_strategy_param("MIN_INTERVAL_DAYS")
VOLATILITY_OVERRIDE_PCT = get_strategy_param("VOLATILITY_OVERRIDE_PCT")


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

# V22.0: 加载状态，并重新计算持仓和成本 (重要步骤)
state = load_state()
state = recalculate_holdings_and_cost(state)
# save_state(state) # 避免在 rerurn 之前重复保存

# 主数据表格构建
table_data = []
decision_logs = {} 
pie_chart_data = [] # <--- 新增：用于存储饼图数据

progress_bar = st.progress(0, text="计算中...")
total_targets = len(TARGETS)
full_data_frames = {} 

# --- 大盘整体仓位指标计算 (保持不变) ---
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
    
    # V22.0: 从状态中直接读取总成本
    current_total_cost = s["total_cost"]
    
    days_since_last_op_display = '—'
    avg_cost_display = '—'
    pl_pct_display = '—'

    current_decision_log = [] 

    if metrics_result:
        (curr_pe, curr_percentile, avg3, avg_5yr, avg_10yr, df_full, 
         max_dev, min_dev, max_dev_date, min_dev_date) = metrics_result
        
        full_data_frames[fixed_filename_key] = df_full 

        # --- V22.0: 自动回填缺失数据 (使用改进的 find_pe_by_date) ---
        for trade in s['history']:
            if trade['pe'] is None or trade['close'] is None or np.isnan(trade.get('pe', np.nan)):
                new_pe, new_close = find_pe_by_date(df_full, trade['date'])
                if not np.isnan(new_pe) and not np.isnan(new_close):
                    trade['pe'] = round(new_pe, 2)
                    trade['close'] = round(new_close, 2)
                    updated_records_count += 1
        
        # --- V22.0: P&L 计算 (使用新的 calculate_index_pl_metrics) ---
        current_close_index = df_full.iloc[-1]['Close']
        avg_cost, pl_pct, _ = calculate_index_pl_metrics(s, current_close_index, df_full)

        if not np.isnan(avg_cost):
            avg_cost_display = f"{avg_cost:.4f}"
        if not np.isnan(pl_pct):
            pl_pct_display = f"{pl_pct * 100:.2f}%"

        # --- 阶梯买入/时间限制判断 ---
        last_op = s["history"][-1] if s["history"] else None
        time_limit_suppression = False
        
        # ... (此处逻辑与 V21.1 保持一致，但使用 V22.0 的动态参数) ...
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
        
        # ==================== 信号判断逻辑 (含决策日志 - V22.0 使用动态参数) ====================
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
                    # V22.0: 使用动态 STEP_PERCENT
                    required_entry_pe = last_buy_pe * (1 - STEP_PERCENT)
                    current_decision_log.append(f"阶梯买入检查: 上次买入PE {last_buy_pe:.2f}, 下次买入PE阈值 {required_entry_pe:.2f} (要求跌幅 ≥ {STEP_PERCENT*100:.0f}%)。")
                    if curr_pe > required_entry_pe:
                        suppress_by_step = True
                        current_decision_log.append(f"结果: 跌幅不足 {STEP_PERCENT*100:.0f}%，抑制买入。")
                else:
                    current_decision_log.append(f"阶梯买入检查: 无持仓或无上次买入PE，不检查跌幅限制。")
                        
                if suppress_by_step:
                    signal = f"⏸️ 观望 (跌幅不足 {STEP_PERCENT*100:.0f}%)"
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
            
            # === 新增：最大/最小偏离 ===
            "最大偏离(3年)": f"{max_dev:.1f}%" if not np.isnan(max_dev) else '—',
            "最小偏离(3年)": f"{min_dev:.1f}%" if not np.isnan(min_dev) else '—',
            # =========================
            
            "建议信号": signal,
            "上次操作距今(天)": days_since_last_op_display,
            "平均成本(ETF)": avg_cost_display,
            "浮动盈亏(%)": pl_pct_display,
            "当前持仓(份额)": f"{current_holdings:.2f}", # 改名：份额
            "上次操作日期": last_date, 
            "上次操作PE": f"{last_pe:.2f}" if not np.isnan(last_pe) else '—', 
        })
        
    else:
        # ... (数据加载失败处理保持不变) ...
        decision_logs[code] = ["数据处理失败或文件缺失，无法评估策略。"]
        table_data.append({
            "指数名称": name, 
            "建议信号": "⚠️ 数据处理失败/文件缺失",
            "PE分位点": "—", "偏离度(3年%)": "—", "当前PE": "—", 
            "上次操作距今(天)": '—',
            "平均成本(ETF)": '—', "浮动盈亏(%)": '—',
            "当前持仓(份)": f"{s['holdings']:.1f}", 
            "上次操作日期": last_date, "上次操作PE": "—"
        })

progress_bar.empty()

# === 新增：侧边栏持仓分布图 ===
with st.sidebar:
    st.markdown("---")
    st.markdown("### 🍰 持仓分布 (市值)")
    if pie_chart_data:
        import plotly.express as px
        df_pie = pd.DataFrame(pie_chart_data)
        # 过滤掉 0 值
        df_pie = df_pie[df_pie['value'] > 0]
        if not df_pie.empty:
            fig_pie = px.pie(df_pie, values='value', names='name', hole=0.4)
            fig_pie.update_layout(showlegend=False, margin=dict(t=0, b=0, l=0, r=0), height=250)
            st.plotly_chart(fig_pie, use_container_width=True)
            
            total_asset = df_pie['value'].sum()
            st.caption(f"总持仓市值估算: ¥{total_asset:,.0f}")
        else:
            st.info("暂无持仓数据")
    else:
        st.info("暂无持仓数据")
# ==============================


# --- 检查是否需要保存状态和重新运行 (V22.0 优化) ---
if updated_records_count > 0:
    save_state(state) # 仅保存历史记录，持仓和成本已在 load 时重新计算
    st.success(f"✅ 已自动补录 {updated_records_count} 条交易记录的 PE/点位数据!")
    st.cache_data.clear() 
    time.sleep(1)
    st.rerun()

# ... (核心指标显示区保持不变) ...

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



# --- 详细的决策依据显示 (修改版：下拉菜单选择) ---
st.markdown("---")
st.subheader("🔍 详细决策依据")

# 创建两列，左侧放选择框，右侧留白
col_log_select, _ = st.columns([1, 2])

with col_log_select:
    # 获取有日志的指数列表
    log_options = list(TARGETS.values())
    selected_log_name = st.selectbox("选择要查看决策详情的指数：", log_options)

# 根据名称找到对应的 Key
selected_log_key = next((k for k, v in TARGETS.items() if v == selected_log_name), None)

with st.container(border=True):
    if selected_log_key and selected_log_key in decision_logs:
        st.markdown(f"#### {selected_log_name} 策略评估日志")
        for log_entry in decision_logs[selected_log_key]:
            #简单的格式化：根据关键词加颜色
            if "建议买入" in log_entry:
                st.markdown(f"- :green[{log_entry}]")
            elif "建议卖出" in log_entry:
                st.markdown(f"- :red[{log_entry}]")
            elif "观望" in log_entry:
                st.markdown(f"- :orange[{log_entry}]")
            else:
                st.markdown(f"- {log_entry}")
    else:
        st.info("该指数暂无决策日志信息。")

            

# --- 交易登记逻辑 (新增交易管理 - V23.4 升级：批量导入支持多指数) ---
st.markdown("---")
st.header("🛒 交易登记与管理 (本地文件模式)")

# V23.4: 新增 "批量导入" 标签页
tab_record, tab_manage, tab_import = st.tabs(["📝 登记新交易", "⚙️ 管理/修改记录", "📤 批量导入"])

# 准备指数名称到文件名的反向映射，用于导入查找
TARGETS_REVERSE = {v: k for k, v in TARGETS.items()}


# ======================= Tab 1: 登记新交易 (保持不变) =======================
with tab_record:
    # 移除 FIXED_AMOUNT_PER_PORTION 和 MAX_UNITS 的引用和显示
    st.markdown("---")

    with st.container(border=True):
        # 调整列宽以更好地适应份额输入模式
        col1, col2, col_fund, col3, col4 = st.columns([2, 1.5, 2.5, 2, 2.5])

        name_options = list(TARGETS.values())

        with col1:
            selected_name_r = st.selectbox("选择指数", name_options, key="select_record_index")
            selected_file_r = next(f for f, n in TARGETS.items() if n == selected_name_r)
            # V23.4: 显示当前持有份额，不再显示份数
            current_holdings = state[selected_file_r].get('holdings', 0.0)
            st.markdown(f"**当前持有份额:** `{current_holdings:.2f} 份`")


        with col2:
            action_r = st.selectbox("操作类型", ["买入", "卖出"], key="select_action")

        with col_fund:
            # V23.3 新增字段：基金名称/代码
            fund_name_r = st.text_input("基金名称/代码 (例: 513050)", value="", key="input_fund_name")

        with col3:
            trade_date_r = st.date_input("成交日期", value=datetime.now().date(), max_value=datetime.now().date(), key="input_date")
            trade_date_str_r = trade_date_r.strftime("%Y-%m-%d")

        with col4:
            trade_price_r = st.number_input("基金净值/成交价", min_value=0.0001, format="%.4f", value=1.0000, step=0.0001, key="input_price")

            # === 核心修改：输入具体份额 ===
            trade_unit_r = st.number_input("交易份额 (Shares)", min_value=0.01, value=100.0, step=10.0, format="%.2f", key="input_unit")

            # 实时计算预估金额显示给用户看
            est_amount = trade_price_r * trade_unit_r
            st.caption(f"交易金额: ¥{est_amount:,.2f}")

    if st.button("提交新记录", type="primary", use_container_width=True):

        # --- 交易前数据准备 ---
        s = state[selected_file_r]
        df_selected_r = full_data_frames.get(selected_file_r)

        if not fund_name_r.strip():
            st.error("请输入基金名称/代码，以便区分追踪同一指数的不同基金！")
            # 不停止程序，只显示错误

        elif df_selected_r is None:
            st.error(f"⚠️ 无法提交记录：数据文件 {selected_file_r} 读取失败。")

        else:
            # 查找 PE/Close
            trade_pe_r, trade_close_r = find_pe_by_date(df_selected_r, trade_date_str_r)
            saved_pe_r = round(trade_pe_r, 2) if not np.isnan(trade_pe_r) else None
            saved_close_r = round(trade_close_r, 2) if not np.isnan(trade_close_r) else None

            # --- 核心买卖逻辑 (V23.4: 份额模式) ---
            if action_r == "买入":
                transaction_r = {
                    "date": trade_date_str_r, "type": action_r, "pe": saved_pe_r,
                    "close": saved_close_r, "price": trade_price_r,
                    "unit": trade_unit_r,   # 直接存入输入的份额
                    "fund_name": fund_name_r,
                    "portions": 0           # 废弃字段
                }
                s["history"].append(transaction_r)

                # 重新计算并保存
                state = recalculate_holdings_and_cost(state)
                if save_state(state):
                    st.success(f"✅ 已记录：{selected_name_r} 买入{trade_unit_r:.2f} 份额。")

            elif action_r == "卖出":
                # 检查持仓是否足够
                if current_holdings >= trade_unit_r:
                    transaction_r = {
                        "date": trade_date_str_r, "type": action_r, "pe": saved_pe_r,
                        "close": saved_close_r, "price": trade_price_r,
                        "unit": trade_unit_r,   # 直接存入输入的份额
                        "fund_name": fund_name_r,
                        "portions": 0
                    }
                    s["history"].append(transaction_r)

                    # 重新计算并保存
                    state = recalculate_holdings_and_cost(state)
                    if save_state(state):
                        st.warning(f"⚠️ 已记录：{selected_name_r} 卖出{trade_unit_r:.2f} 份额。")
                else:
                    st.error(f"份额不足！当前持有 {current_holdings:.2f} 份额，无法卖出 {trade_unit_r} 份额。")

            # 刷新页面以显示最新持仓
            time.sleep(1)
            st.cache_data.clear()
            st.rerun()

st.markdown("---")
st.subheader("历史交易记录 (来自本地文件)")


# 历史记录显示
if 'select_record_index' in st.session_state and st.session_state.select_record_index:
    selected_name = st.session_state.select_record_index
    selected_file = next(f for f, n in TARGETS.items() if n == selected_name)
    holding_info = state[selected_file]

    if holding_info['history']:
        # 确保 date 字段是字符串，避免 to_datetime 转换问题
        df_history = pd.DataFrame([
            {**h, 'date': h['date'].strftime('%Y-%m-%d') if hasattr(h['date'], 'strftime') else h['date']}
            for h in holding_info['history']
        ])

        # V23.4: 只保留 'unit' 和 'fund_name'
        df_display_history = df_history[['date', 'type', 'fund_name', 'price', 'unit', 'pe', 'close']].copy()
        df_display_history = df_display_history.rename(columns={
            'date': '成交日期', 'type': '操作类型', 'fund_name': '基金代码/名称', 'price': 'ETF成交价',
            'unit': '基金份额', 'pe': '成交PE(自动)', 'close': '成交点位(自动)'
        })

        df_display_history = df_display_history.iloc[::-1] # 倒序显示，最新记录在前

        st.dataframe(
            df_display_history.style.format({
                'ETF成交价': "¥ {:.4f}",
                '基金份额': "{:.2f}",
                '成交PE(自动)': "{:.2f}",
                '成交点位(自动)': "{:.2f}"
            }, na_rep='N/A'),
            use_container_width=True,
            hide_index=True
        )
    else:
        st.info(f"当前 {selected_name} 没有交易记录。")
else:
    st.info("请在上方选择一个指数以查看其历史交易记录。")
# ======================= Tab 2: 管理/修改交易记录 (保持不变) =======================
with tab_manage:
    st.markdown("⚠️ **危险操作！** 删除和修改记录将直接影响持仓和成本计算。")

    name_options_m = list(TARGETS.values())
    selected_name_m = st.selectbox("选择要管理记录的指数", name_options_m, key="select_manage_index_m") # 确保 key 唯一
    selected_file_m = next(f for f, n in TARGETS.items() if n == selected_name_m)
    
    s_m = state[selected_file_m]
    
    if not s_m['history']:
        st.info("该指数尚无交易记录可供管理。")
    else:
        # 将历史记录转换为 DataFrame 以便展示索引
        history_df_m_list = [{**h, 'date': h['date'].strftime('%Y-%m-%d') if hasattr(h['date'], 'strftime') else h['date']} for h in s_m['history']]
        history_df_m = pd.DataFrame(history_df_m_list)
        history_df_m['索引'] = history_df_m.index # 添加索引列用于识别记录
        
        # V23.3: 增加 'portions' 和 'fund_name' 列显示
        df_display_m = history_df_m[['索引', 'date', 'type', 'portions', 'fund_name', 'price', 'unit', 'pe', 'close']].copy()
        df_display_m = df_display_m.rename(columns={'date': '成交日期', 'type': '操作类型', 'portions': '交易份数(300元/份)', 'fund_name': '基金代码/名称', 'price': 'ETF成交价', 'unit': '基金份额', 'pe': '成交PE(自动)', 'close': '成交点位(自动)'})
        
        # 格式化 PE/Close/Price
        for col in ['ETF成交价', '成交PE(自动)', '成交点位(自动)', '基金份额', '交易份数(300元/份)']:
             if col in df_display_m.columns:
                 if col == 'ETF成交价':
                     df_display_m[col] = df_display_m[col].apply(lambda x: f"{x:.4f}" if pd.notna(x) and x is not None else 'N/A')
                 else:
                     df_display_m[col] = df_display_m[col].apply(lambda x: f"{x:.2f}" if pd.notna(x) and x is not None else 'N/A')
        
        st.dataframe(df_display_m, use_container_width=True, hide_index=True)

        # --- 删除操作 ---
        st.subheader("删除记录")
        col_del, col_button_del = st.columns([1, 1])
        with col_del:
            index_to_delete = st.number_input("输入要删除的记录行索引 (最左侧列)", min_value=0, max_value=len(history_df_m) - 1, step=1, key="delete_index")
        
        with col_button_del:
            st.markdown("##### ")
            if st.button(f"🔴 确认删除第 {index_to_delete} 行记录", key="confirm_delete_button"):
                if 0 <= index_to_delete < len(s_m['history']):
                    del s_m['history'][index_to_delete]
                    state = recalculate_holdings_and_cost(state) # 立即重新计算
                    save_state(state) # 保存到本地 JSON 文件
                    st.success(f"✅ 记录 {index_to_delete} 已删除，持仓已重新计算。")
                    time.sleep(1)
                    st.cache_data.clear()  
                    st.rerun()
                else:
                    st.error("索引超出范围，请检查输入。")

        st.markdown("---")
        
        # --- 修改操作 (V23.3: 需同时修改 portions, unit, fund_name) ---
        st.subheader("修改记录")
        
        df_selected_m = full_data_frames.get(selected_file_m)

        col_mod_index, col_mod_type, col_mod_date, col_mod_price = st.columns(4)
        
        # 1. 选择要修改的索引
        with col_mod_index:
            index_to_modify = st.number_input("输入要修改的记录行索引", min_value=0, max_value=len(history_df_m) - 1, step=1, key="modify_index")
        
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

            # 4. 修改 ETF 价格和份数/份额
            with col_mod_price:
                new_price = st.number_input("新ETF成交价", min_value=0.0001, format="%.4f", value=record_to_modify.get('price', 1.0000), step=0.0001, key="modify_price")
            
            # V23.3: 允许用户直接修改 'portions' (份数)
            new_portions = st.number_input("新交易份数 (300元/份)", min_value=1, value=int(record_to_modify.get('portions', 1)), step=1, key="modify_portions")
            
            # V23.3: 允许用户直接修改 'unit' (基金份额)
            new_unit = st.number_input("新基金份额 (仅用于卖出平均份额失败时手动调整)", min_value=0.0, value=record_to_modify.get('unit', 1.0), step=0.01, key="modify_unit")
            
            # V23.3: 允许修改基金代码/名称
            new_fund_name = st.text_input("新基金代码/名称", value=record_to_modify.get('fund_name', ''), key="modify_fund_name")

            if st.button(f"🟡 确认修改第 {index_to_modify} 行记录", key="confirm_modify_button"):
                
                # 重新查找新的 PE/Close
                trade_pe_mod, trade_close_mod = find_pe_by_date(df_selected_m, new_date_str)
                saved_pe_mod = round(trade_pe_mod, 2) if not np.isnan(trade_pe_mod) else None
                saved_close_mod = round(trade_close_mod, 2) if not np.isnan(trade_close_mod) else None

                # V23.3: 核心修改逻辑
                if new_type == '买入':
                     # 重新计算基金份额: 份数 * 金额 / 价格
                     final_unit = (new_portions * FIXED_AMOUNT_PER_PORTION) / new_price
                elif new_type == '卖出':
                     final_unit = new_unit 
                     st.warning("⚠️ 卖出记录修改时，基金份额(unit)不会自动重新计算平均份额。请确认您输入的 '新基金份额' 是正确的。")
                else:
                     final_unit = new_unit
                     
                # 更新记录
                s_m['history'][index_to_modify] = {
                    "date": new_date_str,
                    "type": new_type,
                    "pe": saved_pe_mod, 
                    "close": saved_close_mod,
                    "price": new_price, 
                    "unit": final_unit, # 最终基金份额
                    "portions": new_portions, # 最终份数
                    "fund_name": new_fund_name # 基金名称
                }

                state = recalculate_holdings_and_cost(state)
                save_state(state)
                st.success(f"✅ 记录 {index_to_modify} 已更新并重新计算持仓。")
                time.sleep(1)
                st.cache_data.clear() 
                st.rerun()
        else:
            if len(s_m['history']) > 0:
                st.error("索引超出范围，请检查输入。")
# ======================= Tab 3: 批量导入 (V23.4.1 修复 openpyxl 依赖问题) =======================

with tab_import:
    st.header("📤 批量导入交易记录")
    st.markdown("---")
    # 提示用户文件格式，已包含 '份额' 列
    st.info("请确保您的导入文件包含以下表头：**`日期`**, **`操作类型`**, **`净值`**, **`份额`**, **`基金代码`**, **`所属指数`**。")
    # 移除关于 FIXED_AMOUNT_PER_PORTION 的提示

    uploaded_file = st.file_uploader("选择交易记录文件 (.csv 或 .xlsx)", type=["csv", "xlsx"])

    if uploaded_file is not None:
        df_import = None
        file_ext = uploaded_file.name.split('.')[-1].lower()

        try:
            # --- 文件读取逻辑 (V23.4.1 改进错误处理) ---
            if file_ext == 'csv':
                df_import = pd.read_csv(uploaded_file)
            elif file_ext == 'xlsx':
                try:
                    df_import = pd.read_excel(uploaded_file)
                except ImportError as ie:
                    # 捕获 openpyxl 缺失的错误
                    if 'openpyxl' in str(ie):
                        st.error("无法读取 .xlsx 文件。缺少依赖 'openpyxl'。")
                        st.warning("您需要在您的环境中安装 openpyxl 库 (`pip install openpyxl`)，**或者**请将您的文件保存为 **.csv** 格式后重新上传。")
                        st.stop()
                    else:
                        raise # Re-raise if it's another import error
                except Exception as e:
                    st.error(f"读取 .xlsx 文件时发生错误: {e}")
                    st.stop()
            else:
                st.error("不支持的文件格式。请上传 .csv 或 .xlsx 文件。")
                st.stop()

            # Check if df_import was successfully created and is not empty
            if df_import is None or df_import.empty:
                st.error("文件内容为空或无法解析。")
                st.stop()

            # === 修改：列验证加入 '份额' ===
            required_cols = ['日期', '操作类型', '净值', '份额', '基金代码', '所属指数']
            if not all(col in df_import.columns for col in required_cols):
                st.error(f"导入失败：缺失必需列。请包含: {required_cols}")
                st.stop()

            df_import = df_import[required_cols].dropna(subset=required_cols)
            df_import.columns = ['date_str', 'type', 'price', 'unit', 'fund_name', 'index_name']

            st.subheader("待导入记录预览")
            st.dataframe(df_import)

            # 2. 确认按钮
            if st.button(f"确认导入 {len(df_import)} 条记录", type="primary", use_container_width=True):

                # 暂存所有新交易，按指数分组
                new_transactions_by_index = {index_key: [] for index_key in TARGETS.keys()}
                total_transactions_processed = 0

                # --- 交易处理：第一遍，收集并计算份额 ---
                for index, row in df_import.iterrows():

                    try:
                        date_obj = pd.to_datetime(row['date_str']).date()
                        date_str = date_obj.strftime("%Y-%m-%d")
                        trade_type = row['type'].strip()
                        trade_price = float(row['price'])
                        trade_unit = float(row['unit']) # 直接读取份额
                        fund_name = str(row['fund_name']).strip()
                        index_name = str(row['index_name']).strip() # V23.4: 读取指数名称

                        # V23.4: 核心映射
                        index_key = TARGETS_REVERSE.get(index_name)

                        if not index_key:
                            st.warning(f"跳过第 {index+1} 行：指数名称 '{index_name}' 在配置中不存在。")
                            continue

                        if trade_type not in ['买入', '卖出']:
                            st.warning(f"跳过第 {index+1} 行：操作类型 '{trade_type}' 无效。")
                            continue

                        df_full = full_data_frames.get(index_key)
                        if df_full is None:
                            st.warning(f"跳过第 {index+1} 行：指数数据文件 {index_key} 未加载，无法回填 PE。")
                            continue

                        # 查找 PE/Close
                        trade_pe, trade_close = find_pe_by_date(df_full, date_str)
                        saved_pe = round(trade_pe, 2) if not np.isnan(trade_pe) else None
                        saved_close = round(trade_close, 2) if not np.isnan(trade_close) else None

                        # --- 核心逻辑：直接使用导入的 'unit' (份额) ---
                        new_transactions_by_index[index_key].append({
                            "date": date_str,
                            "type": trade_type,
                            "pe": saved_pe,
                            "close": saved_close,
                            "price": trade_price,
                            "unit": trade_unit,   # 使用导入的份额
                            "portions": 0,        # 废弃
                            "fund_name": fund_name
                        })
                        total_transactions_processed += 1

                    except Exception as e:
                        st.error(f"处理第 {index+1} 行 ({row['date_str']}) 时发生错误: {e}")
                        continue

                # --- 最终保存：按指数遍历并保存 ---

                saved_count = 0

                for index_key, new_tx_list in new_transactions_by_index.items():
                    if new_tx_list:
                        s = state[index_key]

                        # 1. 附加新交易
                        s['history'].extend(new_tx_list)

                        # 2. 重新计算所有持仓（关键步骤）
                        state = recalculate_holdings_and_cost(state)
                        saved_count += len(new_tx_list)

                if save_state(state):
                    st.success(f"✅ 成功导入 {saved_count} 条记录！数据已重新计算并保存到本地文件。")
                else:
                    st.error("❌ 导入成功，但保存到本地文件失败。")

                time.sleep(1)
                st.cache_data.clear()
                st.rerun()

            else:
                st.info("没有有效的记录被导入。")

        except Exception as e:
            # 捕获除 openpyxl ImportError 之外的其他错误
            st.error(f"文件读取或处理失败。请检查文件格式是否正确。错误: {e}")
            st.warning("提示：请确保您的文件格式正确（如日期格式），且 Excel 文件中只有**一个工作表**，表头在**第一行**。")     
