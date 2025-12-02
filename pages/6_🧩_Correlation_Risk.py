import streamlit as st
import pandas as pd
import plotly.express as px
import os
from datetime import datetime, timedelta

st.set_page_config(page_title="策略回测实验室", page_icon="🧪", layout="wide")

DATA_DIR = "index_data"

st.title("🧪 策略回测实验室")
st.caption("用历史数据验证：在特定时间段内严格执行策略，收益会如何？")

# 1. 侧边栏配置
with st.sidebar:
    st.header("⚙️ 回测参数")
    
    if not os.path.exists(DATA_DIR):
        st.error(f"❌ 找不到 {DATA_DIR} 文件夹")
        st.stop()

    files = [f for f in os.listdir(DATA_DIR) if f.endswith(".csv")]
    sel_file = st.selectbox("选择回测指数:", files, index=0 if files else None)
    
    st.divider()
    
    # --- 新增：时间选择 ---
    st.subheader("📅 时间范围")
    # 默认回测最近 5 年
    default_start = datetime.now() - timedelta(days=365*5)
    default_end = datetime.now()
    
    start_date = st.date_input("开始日期", value=default_start)
    end_date = st.date_input("结束日期", value=default_end)
    
    if start_date >= end_date:
        st.error("开始日期必须早于结束日期")
    
    st.divider()
    
    buy_threshold = st.slider("买入阈值 (PE分位 < X%)", 0.0, 0.5, 0.20, 0.05)
    sell_threshold = st.slider("卖出阈值 (PE分位 > X%)", 0.5, 1.0, 0.80, 0.05)
    invest_amount = st.number_input("每次定投金额", value=1000.0)
    
    freq_days = st.number_input("定投检查间隔 (天)", value=30, min_value=1)

# 2. 回测核心逻辑
if st.button("🚀 开始回测", type="primary") and sel_file:
    try:
        file_path = os.path.join(DATA_DIR, sel_file)
        df = pd.read_csv(file_path)
        
        # --- 数据清洗 ---
        rename_map = {}
        for c in df.columns:
            c_lower = str(c).lower()
            if 'date' in c_lower or '日期' in c_lower: rename_map[c] = 'Date'
            elif 'close' in c_lower or '收盘' in c_lower: rename_map[c] = 'Close'
            elif ('pe' in c_lower or '市盈率' in c_lower) and '分位' not in c_lower: rename_map[c] = 'pe'
        
        df = df.rename(columns=rename_map)
        
        # ⚠️ 去重保护：防止出现两个 'pe' 列导致的报错
        df = df.loc[:, ~df.columns.duplicated()]
        
        required_cols = ['Date', 'pe', 'Close']
        if not all(c in df.columns for c in required_cols):
            st.error(f"数据缺少必要列，识别结果: {list(df.columns)}")
            st.stop()

        # 类型转换与垃圾字符清洗
        df['Date'] = pd.to_datetime(df['Date'], errors='coerce')
        for col in ['pe', 'Close']:
            if df[col].dtype == object:
                 df[col] = df[col].astype(str).str.replace('=', '').str.replace('"', '').str.replace(',', '')
            df[col] = pd.to_numeric(df[col], errors='coerce')

        df = df.dropna(subset=['Date', 'pe', 'Close']).sort_values('Date').set_index('Date')
        
        if len(df) < 250:
            st.warning("⚠️ 历史数据太少 (<250天)，无法计算有效分位。")
            st.stop()

        # === 关键步骤：先在全量历史数据上计算指标 ===
        # 这样即使你只回测最近1年，PE分位也是基于过去5-10年的历史得出的，这才准确。
        df['rolling_pct'] = df['pe'].rolling(window=1250, min_periods=250).rank(pct=True)
        
        # === 关键步骤：计算完指标后，再截取用户选择的时间段 ===
        mask_date = (df.index >= pd.to_datetime(start_date)) & (df.index <= pd.to_datetime(end_date))
        backtest_df = df.loc[mask_date].copy()
        
        if backtest_df.empty:
            st.warning(f"⚠️ 所选时间段 ({start_date} ~ {end_date}) 内没有数据。请检查 CSV 文件的日期范围。")
            st.write(f"CSV文件日期范围: {df.index.min().date()} ~ {df.index.max().date()}")
            st.stop()

        # 初始化回测变量
        cash = 0.0
        shares = 0.0
        total_invested = 0.0
        history = []
        
        # 模拟基准 (傻瓜定投)
        base_shares = 0.0
        base_invested = 0.0
        
        # 按间隔采样
        # 找到采样点 (确保落在筛选后的区间内)
        # 使用 asof 查找最接近的交易日，避免非交易日问题
        date_range = pd.date_range(start=backtest_df.index.min(), end=backtest_df.index.max(), freq=f'{freq_days}D')
        
        for d in date_range:
            # 在 backtest_df 中找最近的有效交易日（向后搜索）
            # searchsorted 这种方法比较快
            idx = backtest_df.index.searchsorted(d)
            if idx >= len(backtest_df): break
            
            date = backtest_df.index[idx]
            row = backtest_df.loc[date]
            
            price = row['Close']
            pct = row['rolling_pct']
            
            if pd.isna(pct) or pd.isna(price) or price <= 0: continue
            
            # --- 策略组 ---
            action = "hold"
            if pct <= buy_threshold:
                shares += invest_amount / price
                total_invested += invest_amount
                action = "buy"
            elif pct >= sell_threshold:
                if shares > 0:
                    sell_shares = shares * 0.5
                    cash += sell_shares * price
                    shares -= sell_shares
                    action = "sell"
            
            strategy_value = shares * price + cash
            
            # --- 基准组 ---
            base_shares += invest_amount / price
            base_invested += invest_amount
            base_value = base_shares * price
            
            history.append({
                "Date": date,
                "Strategy_Value": strategy_value,
                "Base_Value": base_value,
                "Invested": total_invested,
                "Base_Invested": base_invested,
                "Action": action,
                "PE_Pct": pct,
                "Price": price
            })
            
        if not history:
            st.warning("所选区间内没有产生交易点。")
            st.stop()
            
        res_df = pd.DataFrame(history).set_index("Date")
        res_df = res_df[~res_df.index.duplicated(keep='last')] # 去重保险
        final = res_df.iloc[-1]
        
        # 计算收益率
        ret_strat = (final['Strategy_Value'] - final['Invested']) / final['Invested'] if final['Invested'] > 0 else 0
        ret_base = (final['Base_Value'] - final['Base_Invested']) / final['Base_Invested'] if final['Base_Invested'] > 0 else 0
        
        # 展示结果
        st.success(f"✅ 回测完成！区间: {res_df.index[0].date()} 至 {res_df.index[-1].date()}")
        
        c1, c2, c3 = st.columns(3)
        c1.metric("策略总收益率", f"{ret_strat*100:.2f}%", f"总投入: ¥{final['Invested']:,.0f}")
        c2.metric("傻瓜定投收益率", f"{ret_base*100:.2f}%", f"总投入: ¥{final['Base_Invested']:,.0f}")
        c3.metric("策略超额收益", f"{(ret_strat - ret_base)*100:.2f}%", delta_color="normal")
        
        # 绘图
        st.subheader("📈 累计收益金额对比")
        res_df['策略累计盈亏'] = res_df['Strategy_Value'] - res_df['Invested']
        res_df['基准累计盈亏'] = res_df['Base_Value'] - res_df['Base_Invested']
        
        fig = px.line(res_df, y=["策略累计盈亏", "基准累计盈亏"], 
                      title=f"{sel_file} - 收益走势 ({start_date} ~ {end_date})")
        st.plotly_chart(fig, use_container_width=True)
        
        # 买卖点图
        st.subheader("🎯 交易信号分布")
        buy_pts = res_df[res_df['Action'] == 'buy']
        sell_pts = res_df[res_df['Action'] == 'sell']
        
        fig2 = px.scatter(res_df, y="PE_Pct", x=res_df.index, color_discrete_sequence=['gray'])
        fig2.add_scatter(x=buy_pts.index, y=buy_pts['PE_Pct'], mode='markers', name='买入', marker=dict(color='green', size=10, symbol='triangle-up'))
        fig2.add_scatter(x=sell_pts.index, y=sell_pts['PE_Pct'], mode='markers', name='卖出', marker=dict(color='red', size=10, symbol='triangle-down'))
        
        # 辅助线
        fig2.add_hline(y=buy_threshold, line_dash="dash", line_color="green", annotation_text="买入线")
        fig2.add_hline(y=sell_threshold, line_dash="dash", line_color="red", annotation_text="卖出线")
        fig2.update_layout(title="PE百分位走势与买卖点", yaxis_title="PE历史百分位", xaxis_title="日期")
        
        st.plotly_chart(fig2, use_container_width=True)
        
    except Exception as e:
        st.error(f"❌ 回测出错: {str(e)}")
