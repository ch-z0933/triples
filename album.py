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
    # 這裡會讀取你在 Streamlit Cloud Secrets 設定的 gcp_service_account
    creds_dict = dict(st.secrets["gcp_service_account"])
    creds = Credentials.from_service_account_info(creds_dict, scopes=scope)
    client = gspread.authorize(creds)
    # 請確保你的 Google Sheet 檔名為 "tripleS_Neptune_Sales"
    return client.open("tripleS_Neptune_Sales").sheet1

try:
    sheet = init_connection()
except Exception as e:
    st.error(f"雲端連線失敗，但程式將繼續運行。錯誤: {e}")
    sheet = None

# --- 2. 原始設定區 ---
st.set_page_config(page_title="tripleS Neptune ", layout="wide")
st.title("🌌 tripleS Neptune 台北應募 - 即時銷售")

# 這次活動的 API 網址
API_URL = "https://www.kmonstar.com.tw/products/%E6%87%89%E5%8B%9F-260425-triples-neptune-sss-summit-in-asia-%E7%89%B9%E5%88%A5%E4%B8%80%E5%B0%8D%E4%B8%80%E5%92%95-objekt-%E6%B4%BB%E5%8B%95-in-taipei.json"

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Accept": "application/json",
}

# --- 3. 初始化資料 (加入雲端載入邏輯) ---
if 'history' not in st.session_state:
    st.session_state.history = pd.DataFrame(columns=['時間', '最新總銷量', '變動'])
if 'last_val' not in st.session_state:
    st.session_state.last_val = 0
if 'member_logs' not in st.session_state:
    st.session_state.member_logs = {}
if 'member_last_sales' not in st.session_state:
    st.session_state.member_last_sales = {}

# 【恢復數據】啟動時嘗試從雲端同步歷史紀錄
if 'cloud_synced' not in st.session_state:
    if sheet:
        try:
            # 獲取所有成員清單
            member_names = ["서연 SeoYeon", "나경 NaKyoung", "다현 DaHyun", "코토네 Kotone", "니엔 Nien", "서아 SeoAh"]
            for name in member_names:
                try:
                    m_sheet = sheet.spreadsheet.worksheet(name)
                    records = m_sheet.get_all_records()
                    if records:
                        m_df = pd.DataFrame(records)
                        # 將雲端資料存入 session
                        st.session_state.member_logs[name] = m_df.iloc[::-1] # 最新在上面
                        st.session_state.member_last_sales[name] = int(m_df.iloc[-1]['總銷售量'])
                except:
                    continue # 若無該分頁則跳過
            st.session_state.cloud_synced = True
        except Exception as e:
            st.warning(f"自動恢復雲端數據提醒: {e}")

def get_data():
    try:
        # 加上隨機時間戳防止快取
        res = requests.get(f"{API_URL}?t={int(time.time())}", headers=HEADERS, timeout=10)
        data = res.json()
        total = data.get('total_sold', 0)
        variants = data.get('variants', [])
        
        member_list = []
        for v in variants:
            # 直接抓取 option1 欄位做為名字
            name = v.get('option1', 'Unknown')
            # 銷量邏輯：庫存絕對值
            sales_val = abs(v.get('inventory_quantity', 0))
            
            member_list.append({
                "成員名稱": name,
                "總銷售量": sales_val,
                "狀態": "可應募" if v.get('available') else "完售"
            })
        return total, member_list
    except:
        return None, None

# --- 4. 主程式執行 ---
status_placeholder = st.empty()

while True:
    current_total, members = get_data()
    
    if current_total is not None and members:
        tz = pytz.timezone('Asia/Taipei')
        now = datetime.now(tz).strftime("%H:%M:%S")
        
        # 1. 總銷量異動日誌
        if current_total != st.session_state.last_val:
            diff = current_total - st.session_state.last_val if st.session_state.last_val > 0 else 0
            new_row = pd.DataFrame([{'時間': now, '最新總銷量': current_total, '變動': f"+{diff}"}])
            st.session_state.history = pd.concat([new_row, st.session_state.history], ignore_index=True)
            st.session_state.last_val = current_total

        # 2. 個別成員銷量追蹤
        for m in members:
            name = m['成員名稱']
            current_sales = m['總銷售量']
            
            # 初始化新成員資料
            if name not in st.session_state.member_last_sales:
                st.session_state.member_last_sales[name] = current_sales
                st.session_state.member_logs[name] = pd.DataFrame([
                    {'時間': now, '張數': 0, '狀態': '初始數據', '總銷售量': current_sales}
                ])
            
            # 偵測銷量變化
            last_sales = st.session_state.member_last_sales[name]
            if current_sales != last_sales:
                diff_sales = current_sales - last_sales
                status = "購買" if diff_sales > 0 else "退單/異動"
                
                # 寫入 Google Sheet 相對應分頁
                if sheet:
                    try:
                        member_sheet = sheet.spreadsheet.worksheet(name)
                        member_sheet.append_row([now, diff_sales, status, current_sales])
                    except Exception:
                        pass # 分頁名稱不符時略過

                new_entry = pd.DataFrame([{
                    '時間': now, '張數': diff_sales, '狀態': status, '總銷售量': current_sales
                }])
                st.session_state.member_logs[name] = pd.concat([new_entry, st.session_state.member_logs[name]], ignore_index=True)
                st.session_state.member_last_sales[name] = current_sales

        # --- 5. 畫面渲染 ---
        with status_placeholder.container():
            col1, col2 = st.columns([1, 1.2])
            col1.metric("📊 全體累計銷量", f"{current_total} 份")
            with col2:
                st.write("### 👥 目前各成員統計")
                st.table(pd.DataFrame(members))

            st.divider()
            
            st.write("### 📄 個別應募紀錄")
            m_names = [m['成員名稱'] for m in members]
            tabs = st.tabs(m_names)
            for i, tab in enumerate(tabs):
                m_name = m_names[i]
                with tab:
                    display_df = st.session_state.member_logs.get(m_name, pd.DataFrame())
                    st.dataframe(display_df, use_container_width=True, hide_index=True)

            st.write("### 📜 全體銷售異動日誌")
            st.dataframe(st.session_state.history, use_container_width=True, hide_index=True)

    time.sleep(15) # 每 15 秒更新一次
    st.rerun()
