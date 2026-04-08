import streamlit as st
import requests
import pandas as pd
import time
from datetime import datetime
import pytz
import gspread
from google.oauth2.service_account import Credentials

# --- 1. Google Sheets 核心連線 ---
def init_connection():
    scope = ["https://www.googleapis.com/auth/spreadsheets", "https://www.googleapis.com/auth/drive"]
    creds_dict = dict(st.secrets["gcp_service_account"])
    creds = Credentials.from_service_account_info(creds_dict, scopes=scope)
    client = gspread.authorize(creds)
    return client.open("tripleS_Neptune_Sales")

try:
    gc = init_connection()
except Exception as e:
    st.error(f"雲端連線失敗: {e}")
    gc = None

# --- 2. 原始設定區 ---
st.set_page_config(page_title="tripleS Neptune 雙版監控", layout="wide")
st.title("🌌 tripleS Neptune 台北應募 - 雙版聯動監控")

# 雙來源 API
TW_API = "https://www.kmonstar.com.tw/products/%E6%87%89%E5%8B%9F-260425-triples-neptune-sss-summit-in-asia-%E7%89%B9%E5%88%A5%E4%B8%80%E5%B0%8D%E4%B8%80%E5%92%95-objekt-%E6%B4%BB%E5%8B%95-in-taipei.json"
INTL_API = "https://kmonstar.com/api/v1/event/detail/0ee4a010-3193-474c-85b8-989a1d4c07da"

HEADERS = {"User-Agent": "Mozilla/5.0", "Accept": "application/json"}

# --- 3. 初始化資料 ---
if 'history' not in st.session_state:
    st.session_state.history = pd.DataFrame(columns=['時間', '來源', '最新總銷量', '變動'])
if 'member_logs' not in st.session_state:
    st.session_state.member_logs = {}
# 分別記錄兩版的最後銷量
if 'last_tw_sales' not in st.session_state:
    st.session_state.last_tw_sales = {}
if 'last_intl_sales' not in st.session_state:
    st.session_state.last_intl_sales = {}

# 同步函數：讀取 Google Sheets 歷史
def sync_from_cloud(names):
    if gc:
        for name in names:
            if name not in st.session_state.member_logs or st.session_state.member_logs[name].empty:
                try:
                    wks = gc.worksheet(name)
                    data = wks.get_all_records()
                    if data:
                        df = pd.DataFrame(data)
                        df['張數'] = pd.to_numeric(df['張數'], errors='coerce').fillna(0)
                        st.session_state.member_logs[name] = df.sort_index(ascending=False)
                        # 初始基準設為 0，等第一次抓 API 再更新
                    else:
                        st.session_state.member_logs[name] = pd.DataFrame(columns=['時間', '張數', '來源', '總銷量'])
                except:
                    st.session_state.member_logs[name] = pd.DataFrame(columns=['時間', '張數', '來源', '總銷量'])

def get_all_data():
    tw_data = {}
    intl_data = {}
    
    # 這是國際版 API 必須要有的「通行證」標頭
    COMPLEX_HEADERS = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
        "Accept": "application/json, text/plain, */*",
        "Accept-Language": "zh-TW,zh;q=0.9,en-US;q=0.8,en;q=0.7",
        "Origin": "https://kmonstar.com",
        "Referer": "https://kmonstar.com/event/detail/0ee4a010-3193-474c-85b8-989a1d4c07da", # 加上來源頁面
        "Cache-Control": "no-cache",
        "Pragma": "no-cache"
    }

    # 1. 台灣版抓取 (保持不變)
    try:
        res_tw = requests.get(f"{TW_API}?t={int(time.time())}", headers=COMPLEX_HEADERS, timeout=10)
        if res_tw.status_code == 200:
            tw_json = res_tw.json()
            for v in tw_json.get('variants', []):
                tw_data[v['option1']] = abs(v.get('inventory_quantity', 0))
    except: pass

    # 2. 國際版抓取 (模擬瀏覽器存取)
    try:
        # 使用 Session 會話來維持連線穩定度
        session = requests.Session()
        res_intl = session.get(f"{INTL_API}", headers=COMPLEX_HEADERS, timeout=15)
        
        if res_intl.status_code == 200:
            intl_json = res_intl.json()
            
            # 根據你提供的截圖，我們直接從 data 層級裡面找
            data_body = intl_json.get('data', {})
            
            # 判斷 data 是不是我們要的格式
            if isinstance(data_body, dict):
                options = data_body.get('options', [])
                if options:
                    for o in options:
                        name = o.get('option_name')
                        sales = o.get('sales_count', 0)
                        if name:
                            intl_data[name] = sales
                else:
                    # 再次防錯：如果 options 不在裡面，印出 data 內部的所有 key
                    st.write(f"DEBUG - Data 內部的欄位有: {list(data_body.keys())}")
            else:
                st.write(f"DEBUG - Data 格式異常: {type(data_body)}")
        else:
            st.warning(f"國際版 API 連線不成功，狀態碼: {res_intl.status_code}")
    except Exception as e:
        st.error(f"國際版抓取發生錯誤: {e}")
            
    return tw_data, intl_data
    
# --- 4. 主程式執行 ---
status_placeholder = st.empty()

while True:
    tw_res, intl_res = get_all_data()
    
    if tw_res is not None and intl_res is not None:
        all_names = list(set(list(tw_res.keys()) + list(intl_res.keys())))
        sync_from_cloud(all_names)
        
        tz = pytz.timezone('Asia/Taipei')
        now = datetime.now(tz).strftime("%H:%M:%S")
        
        # 核心對比邏輯
        for name in all_names:
            tw_now = tw_res.get(name, 0)
            intl_now = intl_res.get(name, 0)
            
            # 初始化
            if name not in st.session_state.last_tw_sales:
                st.session_state.last_tw_sales[name] = tw_now
                st.session_state.last_intl_sales[name] = intl_now
                continue
            
            # 偵測台灣版變動
            diff_tw = tw_now - st.session_state.last_tw_sales[name]
            if diff_tw != 0:
                source = "台灣版"
                total_m = tw_now + intl_now
                if gc:
                    try: gc.worksheet(name).append_row([now, diff_tw, source, total_m])
                    except: pass
                new_entry = pd.DataFrame([{'時間': now, '張數': diff_tw, '來源': source, '總銷量': total_m}])
                st.session_state.member_logs[name] = pd.concat([new_entry, st.session_state.member_logs[name]], ignore_index=True)
                st.session_state.last_tw_sales[name] = tw_now
            
            # 偵測國際版變動
            diff_intl = intl_now - st.session_state.last_intl_sales[name]
            if diff_intl != 0:
                source = "國際版"
                total_m = tw_now + intl_now
                if gc:
                    try: gc.worksheet(name).append_row([now, diff_intl, source, total_m])
                    except: pass
                new_entry = pd.DataFrame([{'時間': now, '張數': diff_intl, '來源': source, '總銷量': total_m}])
                st.session_state.member_logs[name] = pd.concat([new_entry, st.session_state.member_logs[name]], ignore_index=True)
                st.session_state.last_intl_sales[name] = intl_now

        # --- 5. 畫面渲染 ---
        with status_placeholder.container():
            st.write("### 👥 雙版合算總統計")
            summary = []
            for n in all_names:
                tw = tw_res.get(n, 0)
                intl = intl_res.get(n, 0)
                summary.append({"成員名稱": n, "台灣版": tw, "國際版": intl, "總計銷量": tw + intl})
            st.table(pd.DataFrame(summary).sort_values("總計銷量", ascending=False))

            st.divider()
            
            tabs = st.tabs(all_names)
            for i, tab in enumerate(tabs):
                m_name = all_names[i]
                with tab:
                    log_df = st.session_state.member_logs.get(m_name, pd.DataFrame())
                    cl, cr = st.columns(2)
                    with cl:
                        st.write("🕒 **合併時間紀錄**")
                        if not log_df.empty:
                            st.dataframe(log_df[['時間', '張數', '來源']], use_container_width=True, hide_index=True)
                    with cr:
                        st.write("🏆 **單筆排行 (不分版本)**")
                        if not log_df.empty:
                            rank_df = log_df[log_df['張數'] > 0].copy()
                            if not rank_df.empty:
                                rank_df = rank_df.sort_values("張數", ascending=False).reset_index(drop=True)
                                rank_df.index = rank_df.index + 1
                                rank_display = pd.DataFrame({
                                    "排名": [f"第 {i} 名" for i in rank_df.index],
                                    "單筆張數": rank_df['張數'].values,
                                    "來源": rank_df['來源'].values
                                })
                                st.table(rank_display)

    time.sleep(15)
    st.rerun()
