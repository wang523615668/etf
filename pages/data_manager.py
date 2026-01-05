import os
import pandas as pd
from datetime import datetime, timedelta

DATA_DIR = "market_data_cache" # 数据存储文件夹
if not os.path.exists(DATA_DIR):
    os.makedirs(DATA_DIR)

def get_data_with_cache(token, code, years=10):
    """
    智能增量更新函数：
    1. 优先读本地 CSV
    2. 如果本地有数据，只向 API 请求最新缺失日期的部分
    3. 如果本地无数据，则全量请求
    """
    file_path = os.path.join(DATA_DIR, f"{code}.csv")
    end_date = datetime.now()
    
    # --- 1. 读取本地数据 ---
    local_df = pd.DataFrame()
    last_date = None
    
    if os.path.exists(file_path):
        try:
            local_df = pd.read_csv(file_path)
            local_df["date"] = pd.to_datetime(local_df["date"])
            local_df = local_df.set_index("date").sort_index()
            if not local_df.empty:
                last_date = local_df.index[-1]
        except Exception:
            pass # 如果文件损坏，就当做不存在，重新下载

    # --- 2. 确定 API 请求的开始时间 ---
    if last_date:
        # 如果有本地数据，从本地最后一天 + 1天开始请求
        start_request_date = last_date + timedelta(days=1)
        # 如果本地数据已经是最新（比如今天是周日，最后数据是周五），则无需请求
        if start_request_date.date() > end_date.date():
            return local_df, "local_cache"
        
        # 增量模式：不需要回溯 years，只需要补齐最近几天
        req_start_date = start_request_date
        mode = "增量更新"
    else:
        # 全量模式
        if years > 10:
            req_start_date = datetime(2005, 1, 1)
        else:
            req_start_date = end_date - timedelta(days=years * 365 + 60)
        mode = "全量下载"

    # --- 3. 发起 API 请求 (复用您之前的 fetch 逻辑) ---
    # 如果请求时间已经在今天之后（未来），直接返回本地数据
    if req_start_date > end_date:
        return local_df, "local_latest"

    print(f"[{code}] 正在{mode}... 起点: {req_start_date.date()}")
    
    # 调用您原本的 fetch_comprehensive_data，但修改其内部 start_date 逻辑
    # 注意：这里需要稍微修改一下您的 fetch 函数，让它支持传入具体的 start_date
    new_data, msg = fetch_from_api_logic(token, code, req_start_date, end_date)

    if new_data is None or new_data.empty:
        # API 没返回数据 (可能这几天没开盘)，直接返回本地数据
        return local_df, "no_new_data"

    # --- 4. 合并数据并保存 ---
    if not local_df.empty:
        # 过滤掉重复日期 (以防万一)
        new_data = new_data[~new_data.index.isin(local_df.index)]
        if new_data.empty:
             return local_df, "local_latest"
        final_df = pd.concat([local_df, new_data]).sort_index()
    else:
        final_df = new_data

    # 保存到 CSV
    final_df.to_csv(file_path)
    
    return final_df, "updated"

# --- 辅助：将原 API 逻辑剥离出来，接受具体日期 ---
def fetch_from_api_logic(token, code, start_date, end_date):
    """
    这是您原本 fetch_comprehensive_data 的核心逻辑，
    只是把 years 参数换成了 start_date 和 end_date
    """
    # ... (这里放您原本的 requests 请求代码，分段逻辑 fetch_chunk 等) ...
    # ... 确保 payload['startDate'] = start_date ...
    # 为了演示简洁，此处省略具体请求代码，直接使用您之前的逻辑即可
    # 返回: DataFrame, msg
    pass
