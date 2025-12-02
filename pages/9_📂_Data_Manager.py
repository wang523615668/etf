# pages/9_📂_Data_Manager.py (V25.19 - 修复列名冲突+强力去重)

import streamlit as st
import pandas as pd
import os
import time
import glob
from datetime import datetime

# ================= 配置 =================
DATA_DIR = "index_data"
if not os.path.exists(DATA_DIR):
    os.makedirs(DATA_DIR)

# 目标指数列表 (匹配规则)
TARGETS_MAP = {
    "中证全指.csv": ["中证全指", "000985", "全A"],
    "沪深300.csv": ["沪深300", "000300"],
    "中证500.csv": ["中证500", "000905"],
    "上证50.csv": ["上证50", "000016"],
    "创业板指.csv": ["创业板", "399006"],
    
    "全指医药.csv": ["全指医药", "医药卫生", "000991", "医药"],
    "养老产业.csv": ["养老", "399812"],
    "中证红利.csv": ["红利", "000922"],
    "中证环保.csv": ["环保", "000827"],
    "中证传媒.csv": ["传媒", "399971"],
    "全指金融.csv": ["全指金融", "金融", "000992"],
    "证券公司.csv": ["证券", "399975"],
    "全指消费.csv": ["全指消费", "可选消费", "000990", "消费"],
    "全指信息.csv": ["全指信息", "信息技术", "000993", "信息"],
    "中证医疗.csv": ["医疗", "399989"],
    "中证白酒.csv": ["白酒", "399997"],
}

st.set_page_config(page_title="数据维护后台", page_icon="📂", layout="wide")

st.title("📂 离线数据维护中心")
st.info("💡 修复版 V25.19：解决了列名冲突（DataFrame object has no attribute dtype）问题。")
st.markdown("---")

# ================= 功能1：拖拽上传与自动归档 =================
st.subheader("📤 第一步：上传新数据")

uploaded_files = st.file_uploader("拖入文件 (支持多选)", type=['csv'], accept_multiple_files=True)

if uploaded_files:
    success_count = 0
    fail_count = 0
    
    progress_bar = st.progress(0)
    status_text = st.empty()
    
    for i, file in enumerate(uploaded_files):
        # 1. 匹配文件名
        matched_target = None
        for target_filename, keywords in TARGETS_MAP.items():
            for kw in keywords:
                if kw in file.name:
                    matched_target = target_filename
                    break
            if matched_target: break
        
        status_text.text(f"正在处理: {file.name} ...")
        
        if matched_target:
            try:
                # 尝试读取 (兼容不同编码)
                try:
                    df = pd.read_csv(file, encoding='utf-8')
                except:
                    file.seek(0)
                    df = pd.read_csv(file, encoding='gbk')
                
                # 2. 智能列名映射
                rename_dict = {}
                for col in df.columns:
                    c = str(col).lower()
                    if "date" in c or "日期" in c: rename_dict[col] = "Date"
                    elif "pe" in c or "市盈率" in c: 
                        if "分位" not in c: rename_dict[col] = "pe"
                    elif "分位" in c: rename_dict[col] = "pe_percentile"
                    elif "close" in c or "收盘" in c or "点位" in c: rename_dict[col] = "Close"
                
                df = df.rename(columns=rename_dict)
                
                # 3. ⚠️ 核心修复：立即去重！
                # 防止有多个列都被命名为 'pe'，导致 df['pe'] 返回 DataFrame 而不是 Series
                df = df.loc[:, ~df.columns.duplicated()]
                
                # 4. 强力数据清洗
                if "Date" in df.columns and "pe" in df.columns:
                    
                    # A. 清洗 Excel 垃圾符号 (="23.5", 1,000)
                    cols_to_clean = ['pe', 'Close', 'pe_percentile']
                    for col in cols_to_clean:
                        if col in df.columns: # 必须先检查列是否存在
                            if df[col].dtype == object:
                                df[col] = df[col].astype(str).str.replace('=', '').str.replace('"', '').str.replace(',', '')
                            df[col] = pd.to_numeric(df[col], errors='coerce')
                    
                    # B. 日期强转
                    df['Date'] = pd.to_datetime(df['Date'], errors='coerce')
                    
                    # C. 删除无效行 (空日期、空PE)
                    df = df.dropna(subset=['Date', 'pe'])
                    
                    # D. 格式化与去重
                    df['Date'] = df['Date'].dt.strftime('%Y-%m-%d')
                    df = df.sort_values("Date").drop_duplicates(subset=["Date"], keep='last')
                    
                    # 5. 保存
                    save_path = os.path.join(DATA_DIR, matched_target)
                    df.to_csv(save_path, index=False, encoding='utf-8-sig')
                    
                    st.success(f"✅ **{file.name}** -> 识别为 **{matched_target}** (清洗后剩余 {len(df)} 条)")
                    success_count += 1
                else:
                    st.error(f"❌ {file.name}: 缺少必要列，请检查是否包含'日期'和'PE'")
                    fail_count += 1
                    
            except Exception as e:
                st.error(f"❌ {file.name}: 处理失败 - {str(e)}")
                fail_count += 1
        else:
            st.warning(f"⚠️ {file.name}: 无法识别是哪个指数，文件名需包含如 '白酒'、'沪深300' 等关键词")
            fail_count += 1
            
        progress_bar.progress((i + 1) / len(uploaded_files))
    
    status_text.text("所有文件处理完毕！")
    if success_count > 0:
        st.balloons()
        time.sleep(2)
        st.rerun()

# ================= 功能2：状态监控 =================
st.markdown("---")
st.subheader("📊 数据状态一览")

status_data = []
now = datetime.now()

for filename in TARGETS_MAP.keys():
    file_path = os.path.join(DATA_DIR, filename)
    index_name = filename.replace(".csv", "")
    
    status = "❌ 缺失"
    data_date_str = "—"
    
    if os.path.exists(file_path):
        try:
            # 快速读取检查
            df_check = pd.read_csv(file_path)
            if not df_check.empty and 'Date' in df_check.columns:
                last_date_val = df_check['Date'].iloc[-1]
                last_date = pd.to_datetime(last_date_val)
                data_date_str = last_date.strftime("%Y-%m-%d")
                days_lag = (now - last_date).days
                
                if days_lag <= 7: status = "🟢 新鲜"
                elif days_lag <= 30: status = "🟡 较旧"
                else: status = f"🔴 过期 ({days_lag}天)"
            else:
                status = "⚪ 空文件"
        except:
            status = "❌ 损坏"

    status_data.append({
        "指数": index_name,
        "状态": status,
        "最新日期": data_date_str
    })

st.dataframe(
    pd.DataFrame(status_data).style.applymap(
        lambda v: 'background-color: #ffe6e6' if '🔴' in str(v) or '❌' in str(v) else 
                 ('background-color: #e6fffa' if '🟢' in str(v) else ''), 
        subset=['状态']
    ),
    use_container_width=True,
    height=600
)
