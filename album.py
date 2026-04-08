import streamlit as st
import requests
import pandas as pd
import time
from datetime import datetime
import pytz
import gspread  # 新增
from google.oauth2.service_account import Credentials  # 新增

# --- 1. Google Sheets 核心連線 (不更動你原本的邏輯，僅外掛連線) ---
def init_connection():
    scope = ["https://www.googleapis.com/auth/spreadsheets", "https://www.googleapis.com/auth/drive"]
    creds_dict = dict(st.secrets["gcp_service_account"])
    creds = Credentials.from_service_account_info(creds_dict, scopes=scope)
    client = gspread.authorize(creds)
    # 這裡請確認你的試算表名稱，若不同請修改此處
    return client.open("ITZY_Sales_Data").sheet1

try:
    sheet = init_connection()
except Exception as e:
    st.error(f"雲端連線失敗，但程式將繼續運行。錯誤: {e}")
    sheet = None

# --- 2. 原始設定區 ---
st.set_page_config(page_title="ITZY 即時戰情室", layout="wide")
st.title("🔥 ITZY 台北合照活動 - 即時銷售監控")

API_URL = "https://www.kmonstar.com.tw/products/%E6%87%89%E5%8B%9F-260227-itzy-tunnel-vision-%E5%B0%88%E8%BC%AF%E7%99%BC%E8%A1%8C%E7%B4%80%E5%BF%B511%E5%90%88%E7%85%A7%E6%B4%BB%E5%8B%95-in-taipei.json" 

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/144.0.0.0 Safari/537.36",
    "Accept": "application/json",
}

# --- 3. 初始化資料 (加入雲端載入邏輯，確保重整不歸零) ---
if 'history' not in st.session_state:
    st.session_state.history = pd.DataFrame(columns=['時間', '最新總銷量', '變動'])
if 'last_val' not in st.session_state:
    st.session_state.last_val = 0
if 'member_logs' not in st.session_state:
    st.session_state.member_logs = {}
if 'member_last_sales' not in st.session_state:
    st.session_state.member_last_sales = {}

# 【新增】啟動時自動從雲端恢復數據
if 'cloud_synced' not in st.session_state:
    if sheet:
        try:
            for name in ["YEJI", "LIA", "RYUJIN", "CHAERYEONG", "YUNA"]:
                try:
                    # 分別讀取每個分頁的紀錄
                    m_sheet = sheet.spreadsheet.worksheet(name)
                    records = m_sheet.get_all_records()
                    if records:
                        m_df = pd.DataFrame(records)
                        st.session_state.member_logs[name] = m_df.iloc[::-1]
                        st.session_state.member_last_sales[name] = int(m_df.iloc[-1]['總銷售量'])
                except:
                    # 如果某個成員還沒有分頁，就跳過
                    continue
            st.session_state.cloud_synced = True
        except Exception as e:
            st.error(f"恢復分頁數據失敗: {e}")

def get_data():
    try:
        res = requests.get(f"{API_URL}?t={int(time.time())}", headers=HEADERS, timeout=10)
        data = res.json()
        total = data.get('total_sold', 0)
        variants = data.get('variants', [])
        
        member_list = []
        for v in variants:
            full_title = v.get('title', '')
            # 保留你原本的名字處理邏輯
            name = full_title.split('/')[0].strip().replace('예지 ', '').replace('리아 ', '').replace('류진 ', '').replace('채령 ', '').replace('유나 ', '')
            
            sales_val = abs(v.get('inventory_quantity', 0))
            member_list.append({
                "成員/選項": name,
                "總銷售量": sales_val,
                "價格": v.get('price')
            })
        return total, member_list
    except:
        return None, None

# --- 4. 主程式執行 ---
status_placeholder = st.empty()
log_placeholder = st.empty()

while True:
    current_total, members = get_data()
    
    if current_total is not None and members:
        tz = pytz.timezone('Asia/Taipei')
        now = datetime.now(tz).strftime("%H:%M:%S")
        
        # 1. 處理總銷售量日誌
        if current_total != st.session_state.last_val:
            diff = current_total - st.session_state.last_val if st.session_state.last_val > 0 else 0
            new_row = pd.DataFrame([{'時間': now, '最新總銷量': current_total, '變動': f"+{diff}"}])
            st.session_state.history = pd.concat([new_row, st.session_state.history], ignore_index=True)
            st.session_state.last_val = current_total

        # 2. 處理五個成員個別的紀錄表
        for m in members:
            name = m['成員/選項']
            current_sales = m['總銷售量']
            
            if name not in st.session_state.member_last_sales:
                st.session_state.member_last_sales[name] = current_sales
                st.session_state.member_logs[name] = pd.DataFrame([
                    {'時間': now, '成員名稱': name, '張數': 0, '狀態': '初始數據', '總銷售量': current_sales}
                ])
            
            last_sales = st.session_state.member_last_sales[name]
            if current_sales != last_sales:
                diff_sales = current_sales - last_sales
                status = "購買" if diff_sales > 0 else "退掉"
                
                # --- 修改這裡：動態選擇分頁 ---
                if sheet:
                    try:
                        # 根據成員名字開啟對應的工作表 (例如開啟名為 "YEJI" 的分頁)
                        member_sheet = sheet.spreadsheet.worksheet(name)
                        member_sheet.append_row([now, name, diff_sales, status, current_sales])
                    except Exception as e:
                        st.warning(f"寫入分頁 {name} 失敗: {e}")

                new_entry = pd.DataFrame([{
                    '時間': now, 
                    '成員名稱': name,
                    '張數': diff_sales, 
                    '狀態': status, 
                    '總銷售量': current_sales
                }])
                st.session_state.member_logs[name] = pd.concat([new_entry, st.session_state.member_logs[name]], ignore_index=True)
                st.session_state.member_last_sales[name] = current_sales

        # --- 畫面渲染 (完全維持你原本的設計) ---
        with status_placeholder.container():
            col1, col2 = st.columns([1, 1])
            col1.metric("📊 目前即時總銷量", f"{current_total} 份")
            with col2:
                st.write("### 👥 各成員即時銷售狀況")
                st.table(pd.DataFrame(members))

            st.write("### 📄 成員個別購買紀錄表")
            member_tabs = st.tabs([m['成員/選項'] for m in members])
            for i, tab in enumerate(member_tabs):
                m_name = members[i]['成員/選項']
                with tab:
                    # 顯示資料，但不顯示內部用的「成員名稱」欄位
                    display_df = st.session_state.member_logs[m_name]
                    st.dataframe(display_df, use_container_width=True)

        with log_placeholder.container():
            st.write("### 📜 全體銷售異動日誌")
            st.dataframe(st.session_state.history, use_container_width=True)

    time.sleep(10)
    st.rerun()

