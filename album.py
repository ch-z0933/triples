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
    return client.open("tripleS_Neptune_Sales").sheet1

try:
    sheet = init_connection()
except Exception as e:
    st.error(f"雲端連線失敗: {e}")
    sheet = None

# --- 2. 原始設定區 ---
st.set_page_config(page_title="tripleS Neptune 戰情室", layout="wide")
st.title("🌌 tripleS Neptune 台北應募 - 即時銷售監控")

API_URL = "https://www.kmonstar.com.tw/products/%E6%87%89%E5%8B%9F-260425-triples-neptune-sss-summit-in-asia-%E7%89%B9%E5%88%A5%E4%B8%80%E5%B0%8D%E4%B8%80%E5%92%95-objekt-%E6%B4%BB%E5%8B%95-in-taipei.json"

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Accept": "application/json",
}

# --- 3. 初始化資料 ---
if 'history' not in st.session_state:
    st.session_state.history = pd.DataFrame(columns=['時間', '最新總銷量', '變動'])
if 'last_val' not in st.session_state:
    st.session_state.last_val = 0
if 'member_logs' not in st.session_state:
    st.session_state.member_logs = {}
if 'member_last_sales' not in st.session_state:
    st.session_state.member_last_sales = {}

def get_data():
    try:
        res = requests.get(f"{API_URL}?t={int(time.time())}", headers=HEADERS, timeout=10)
        data = res.json()
        total = data.get('total_sold', 0)
        variants = data.get('variants', [])
        member_list = []
        for v in variants:
            name = v.get('option1', 'Unknown')
            sales_val = abs(v.get('inventory_quantity', 0))
            member_list.append({
                "成員名稱": name,
                "總銷售量": sales_val
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
        
        # 總銷量異動
        if current_total != st.session_state.last_val:
            diff = current_total - st.session_state.last_val if st.session_state.last_val > 0 else 0
            new_row = pd.DataFrame([{'時間': now, '最新總銷量': current_total, '變動': f"+{diff}"}])
            st.session_state.history = pd.concat([new_row, st.session_state.history], ignore_index=True)
            st.session_state.last_val = current_total

        # 個別成員銷量處理
        for m in members:
            name = m['成員名稱']
            current_sales = m['總銷售量']
            
            if name not in st.session_state.member_last_sales:
                st.session_state.member_last_sales[name] = current_sales
                # 初始紀錄 (若目前已經有銷量，視為第一筆)
                st.session_state.member_logs[name] = pd.DataFrame([
                    {'時間': '初始', '張數': current_sales, '狀態': '目前銷量', '總銷售量': current_sales}
                ]) if current_sales > 0 else pd.DataFrame(columns=['時間', '張數', '狀態', '總銷售量'])
            
            last_sales = st.session_state.member_last_sales[name]
            if current_sales != last_sales:
                diff_sales = current_sales - last_sales
                status = "購買" if diff_sales > 0 else "異動"
                
                if sheet:
                    try:
                        member_sheet = sheet.spreadsheet.worksheet(name)
                        member_sheet.append_row([now, diff_sales, status, current_sales])
                    except: pass

                new_entry = pd.DataFrame([{'時間': now, '張數': diff_sales, '狀態': status, '總銷售量': current_sales}])
                st.session_state.member_logs[name] = pd.concat([new_entry, st.session_state.member_logs[name]], ignore_index=True)
                st.session_state.member_last_sales[name] = current_sales

        # --- 5. 畫面渲染 ---
        with status_placeholder.container():
            col1, col2 = st.columns([1, 1.2])
            col1.metric("📊 全體累計總銷量", f"{current_total} 份")
            with col2:
                st.write("### 👥 目前各成員統計")
                # 這裡只顯示名稱與銷量，不顯示狀態
                st.table(pd.DataFrame(members))

            st.divider()
            
            st.write("### 📄 個別應募紀錄與排行")
            m_names = [m['成員名稱'] for m in members]
            # 建立對應的銷量數字供 Tab 顯示
            m_sales_map = {m['成員名稱']: m['總銷售量'] for m in members}
            
            tabs = st.tabs([f"{name} ({m_sales_map[name]}張)" for name in m_names])
            
            for i, tab in enumerate(tabs):
                m_name = m_names[i]
                current_m_total = m_sales_map[m_name]
                
                with tab:
                    # 顯示該成員目前的累積總張數
                    st.metric(f"{m_name} 累計張數", f"{current_m_total} 張")
                    
                    log_df = st.session_state.member_logs.get(m_name, pd.DataFrame())
                    
                    c_left, c_right = st.columns(2)
                    
                    with c_left:
                        st.write("🕒 **單筆時間紀錄**")
                        if not log_df.empty:
                            display_log = log_df[['時間', '張數']].copy()
                            display_log.columns = ['時間', '單筆訂單張數']
                            st.dataframe(display_log, use_container_width=True, hide_index=True)
                        else:
                            st.info("尚無紀錄")

                    with c_right:
                        st.write("🏆 **單筆訂單張數排行**")
                        if not log_df.empty:
                            # 篩選掉 0 或負數的異常數據進行排行
                            rank_df = log_df[log_df['張數'] > 0][['張數']].copy()
                            if not rank_df.empty:
                                rank_df = rank_df.sort_values(by='張數', ascending=False).reset_index(drop=True)
                                rank_df.index = rank_df.index + 1
                                rank_df.index.name = '排名'
                                rank_df.columns = ['單筆訂單張數']
                                st.table(rank_df)
                            else:
                                st.info("尚無購買數據")
                        else:
                            st.info("尚無數據")

            st.write("### 📜 全體銷售異動日誌")
            st.dataframe(st.session_state.history, use_container_width=True, hide_index=True)

    time.sleep(15)
    st.rerun()
