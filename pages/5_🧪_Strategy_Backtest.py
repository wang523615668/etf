import streamlit as st
import pandas as pd
import plotly.express as px
import os

st.set_page_config(page_title="策略回测实验室", page_icon="🧪", layout="wide")

DATA_DIR = "index_data"

st.title("🧪 策略回测实验室")
st.caption("用历史数据验证：如果过去 N 年严格执行策略，收益会如何？")

# 1. 侧边栏配置
with st.sidebar:
    st.header("⚙️ 回测参数")
    
    if not os.path.exists(DATA_DIR):
        st.error(f"❌ 找不到 {DATA_DIR} 文件夹")
        st.stop()

    files = [f for f in os.listdir(DATA_DIR) if f.endswith(".csv")]
    sel_file = st.selectbox("选择回测指数:", files, index=0 if files else None)
    
    buy_threshold = st.slider("买入阈值 (PE分位 < X%)", 0.0, 0.5, 0.20, 0.05)
    sell_threshold = st.slider("卖出阈值 (PE分位 > X%)", 0.5, 1.0, 0.80, 0.05)
    invest_amount = st.number_input("每次定投金额", value=1000.0)
    
    # 定投频率
    freq_days = st.number_input("定投检查间隔 (天)", value=30, min_value=1)

# 2. 回测核心逻辑
if st.button("🚀 开始回测", type="primary") and sel_file:
    try:
        file_path = os.path.join(DATA_DIR, sel_file)
        df = pd.read_csv(file_path)
        
        # --- 强力清洗与去重逻辑 ---
        rename_map = {}
        for c in df.columns:
            c_lower = str(c).lower()
            # 1. 识别日期
            if 'date' in c_lower or '日期' in c_lower: 
                rename_map[c] = 'Date'
            # 2. 识别价格
            elif 'close' in c_lower or '收盘' in c_lower: 
                rename_map[c] = 'Close'
            # 3. 识别PE (排除分位点列)
            elif ('pe' in c_lower or '市盈率' in c_lower) and '分位' not in c_lower: 
                rename_map[c] = 'pe'
        
        df = df.rename(columns=rename_map)
        
        # ⚠️ 关键修复：去除重复列名 (保留第一个 'pe')
        df = df.loc[:, ~df.columns.duplicated()]
        
        # 检查必要列
        required_cols = ['Date', 'pe', 'Close']
        missing_cols = [col for col in required_cols if col not in df.columns]
        
        if missing_cols:
            st.error(f"❌ 数据文件格式无法识别，缺少以下列: {missing_cols}")
            st.write("识别到的列名:", list(df.columns))
            st.stop()

        # 格式转换
        df['Date'] = pd.to_datetime(df['Date'], errors='coerce')
        # 清洗垃圾字符 (如 Excel 的 ="23.5")
        for col in ['pe', 'Close']:
            if df[col].dtype == object:
                 df[col] = df[col].astype(str).str.replace('=', '').str.replace('"', '').str.replace(',', '')
            df[col] = pd.to_numeric(df[col], errors='coerce')

        df = df.dropna(subset=['Date', 'pe', 'Close']).sort_values('Date').set_index('Date')
        
        if len(df) < 250:
            st.warning("⚠️ 历史数据太少 (<250天)，无法计算长期分位。")
            st.stop()

        # 计算滚动分位 (模拟当时视角，使用过去5年/1250天的数据窗口)
        # 如果历史不足5年，min_periods=250 保证至少有1年数据就开始计算
        df['rolling_pct'] = df['pe'].rolling(window=1250, min_periods=250).rank(pct=True)
        
        # 初始化回测变量
        cash = 0.0
        shares = 0.0
        total_invested = 0.0
        history = []
        
        # 模拟傻瓜定投 (基准)
        base_shares = 0.0
        base_invested = 0.0
        
        # 按间隔采样
        sample_dates = df.index[::int(freq_days)]
        
        for date in sample_dates:
            row = df.loc[date]
            price = row['Close']
            pct = row['rolling_pct']
            
            if pd.isna(pct) or pd.isna(price) or price <= 0: continue
            
            # --- 策略组 ---
            action = "hold"
            if pct <= buy_threshold:
                # 低估买入
                shares += invest_amount / price
                total_invested += invest_amount
                action = "buy"
            elif pct >= sell_threshold:
                # 高估卖出 (假设卖出50%持仓)
                if shares > 0:
                    sell_shares = shares * 0.5
                    cash += sell_shares * price
                    shares -= sell_shares
                    action = "sell"
            
            # 记录市值
            strategy_value = shares * price + cash
            
            # --- 基准组 (无脑定投) ---
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
                "PE_Pct": pct
            })
            
        # 结果展示
        if not history:
            st.warning("没有产生任何交易记录。可能是数据区间太短。")
            st.stop()
            
        res_df = pd.DataFrame(history).set_index("Date")
        final = res_df.iloc[-1]
        
        # 计算总收益率
        ret_strat = (final['Strategy_Value'] - final['Invested']) / final['Invested'] if final['Invested'] > 0 else 0
        ret_base = (final['Base_Value'] - final['Base_Invested']) / final['Base_Invested'] if final['Base_Invested'] > 0 else 0
        
        # 核心指标卡片
        st.success(f"回测完成！区间: {res_df.index[0].date()} ~ {res_df.index[-1].date()}")
        
        c1, c2, c3 = st.columns(3)
        c1.metric("策略总收益率", f"{ret_strat*100:.2f}%", f"投入: ¥{final['Invested']:,.0f}")
        c2.metric("傻瓜定投收益率", f"{ret_base*100:.2f}%", f"投入: ¥{final['Base_Invested']:,.0f}")
        c3.metric("策略超额收益", f"{(ret_strat - ret_base)*100:.2f}%", delta_color="normal")
        
        # 绘图：净值曲线
        st.subheader("📈 收益曲线对比")
        # 为了方便对比，显示累计盈亏金额
        res_df['Strategy_Profit'] = res_df['Strategy_Value'] - res_df['Invested']
        res_df['Base_Profit'] = res_df['Base_Value'] - res_df['Base_Invested']
        
        fig = px.line(res_df, y=["Strategy_Profit", "Base_Profit"], 
                      labels={"value": "累计盈亏(元)", "variable": "策略类型"},
                      title="累计盈亏金额对比 (策略 vs 基准)")
        st.plotly_chart(fig, use_container_width=True)
        
        # 绘图：买卖点分布
        st.subheader("🎯 买卖点分布回顾")
        buy_pts = res_df[res_df['Action'] == 'buy']
        sell_pts = res_df[res_df['Action'] == 'sell']
        
        fig2 = px.scatter(res_df, y="PE_Pct", title="买卖时机分析 (基于PE分位)")
        # 绿点买入
        fig2.add_scatter(x=buy_pts.index, y=buy_pts['PE_Pct'], mode='markers', 
                         name='买入点', marker=dict(color='green', size=8, symbol='triangle-up'))
        # 红点卖出
        fig2.add_scatter(x=sell_pts.index, y=sell_pts['PE_Pct'], mode='markers', 
                         name='卖出点', marker=dict(color='red', size=8, symbol='triangle-down'))
        
        # 阈值线
        fig2.add_hline(y=buy_threshold, line_dash="dash", line_color="green", annotation_text="买入线")
        fig2.add_hline(y=sell_threshold, line_dash="dash", line_color="red", annotation_text="卖出线")
        
        fig2.update_layout(yaxis_title="PE历史百分位 (0~1)")
        st.plotly_chart(fig2, use_container_width=True)
        
    except Exception as e:
        st.error(f"❌ 回测发生错误: {str(e)}")
        st.write("建议检查CSV文件格式，或去 Data Manager 重新导入数据。")
