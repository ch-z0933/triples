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
    # 請確保你的 Google Sheet 檔名正確
    return client.open("tripleS_Neptune_Sales")

try:
    gc = init_connection()
except Exception as e:
    st.error(f"雲端連線失敗: {e}")
    gc = None

# --- 2. 原始設定區 ---
st.set_page_config(page_title="tripleS Neptune", layout="wide")
st.title("🌌 tripleS Neptune 台北應募 - 即時銷售監控")

API_URL = "https://www.kmonstar.com.tw/products/%E6%87%89%E5%8B%9F-260425-triples-neptune-sss-summit-in-asia-%E7%89%B9%E5%88%A5%E4%B8%80%E5%B0%8D%E4%B8%80%E5%92%95-objekt-%E6%B4%BB%E5%8B%95-in-taipei.json"
HEADERS = {"User-Agent": "Mozilla/5.0", "Accept": "application/json"}

# --- 3. 初始化資料 & 讀取 Google Sheets 歷史紀錄 ---
if 'history' not in st.session_state:
    st.session_state.history = pd.DataFrame(columns=['時間', '最新總銷量', '變動'])
if 'last_val' not in st.session_state:
    st.session_state.last_val = 0
if 'member_logs' not in st.session_state:
    st.session_state.member_logs = {}
if 'member_last_sales' not in st.session_state:
    st.session_state.member_last_sales = {}

# 【重要：同步邏輯】如果 session 是空的，嘗試從雲端抓回數據
def sync_from_cloud(members):
    if gc:
        for m in members:
            name = m['成員名稱']
            if name not in st.session_state.member_logs or st.session_state.member_logs[name].empty:
                try:
                    wks = gc.worksheet(name)
                    data = wks.get_all_records()
                    if data:
                        df = pd.DataFrame(data)
                        # 確保欄位對齊：時間, 張數, 狀態, 總銷售量
                        st.session_state.member_logs[name] = df.iloc[::-1] # 最新在上面
                        st.session_state.member_last_sales[name] = int(df.iloc[-1]['總銷售量'])
                except:
                    st.session_state.member_logs[name] = pd.DataFrame(columns=['時間', '張數', '狀態', '總銷售量'])

def get_data():
    try:
        res = requests.get(f"{API_URL}?t={int(time.time())}", headers=HEADERS, timeout=10)
        data = res.json()
        total = data.get('total_sold', 0)
        variants = data.get('variants', [])
        member_list = [{"成員名稱": v.get('option1', 'Unknown'), "總銷售量": abs(v.get('inventory_quantity', 0))} for v in variants]
        return total, member_list
    except:
        return None, None

# --- 4. 主程式執行 ---
status_placeholder = st.empty()

while True:
    current_total, members = get_data()
    
    if current_total is not None and members:
        # 第一次運行時同步雲端數據
        sync_from_cloud(members)
        
        tz = pytz.timezone('Asia/Taipei')
        now = datetime.now(tz).strftime("%H:%M:%S")
        
        # A. 總銷量異動
        if current_total != st.session_state.last_val:
            diff = current_total - st.session_state.last_val if st.session_state.last_val > 0 else 0
            label = f"+{diff}" if st.session_state.last_val > 0 else "已連線"
            new_row = pd.DataFrame([{'時間': now, '最新總銷量': current_total, '變動': label}])
            st.session_state.history = pd.concat([new_row, st.session_state.history], ignore_index=True)
            st.session_state.last_val = current_total

        # B. 個別成員銷量監控
        for m in members:
            name = m['成員名稱']
            current_sales = m['總銷售量']
            
            if name not in st.session_state.member_last_sales:
                st.session_state.member_last_sales[name] = current_sales
                continue

            last_sales = st.session_state.member_last_sales[name]
            if current_sales != last_sales:
                diff_sales = current_sales - last_sales
                status = "購買" if diff_sales > 0 else "異動"
                
                # 寫入 Google Sheet
                if gc:
                    try:
                        wks = gc.worksheet(name)
                        wks.append_row([now, diff_sales, status, current_sales])
                    except: pass

                new_entry = pd.DataFrame([{'時間': now, '張數': diff_sales, '狀態': status, '總銷售量': current_sales}])
                st.session_state.member_logs[name] = pd.concat([new_entry, st.session_state.member_logs[name]], ignore_index=True)
                st.session_state.member_last_sales[name] = current_sales

        # --- 5. 畫面渲染 ---
        with status_placeholder.container():
            c1, c2 = st.columns([1, 1.2])
            c1.metric("📊 全體累計總銷量", f"{current_total} 份")
            with c2:
                st.write("### 👥 目前各成員統計")
                st.table(pd.DataFrame(members))

            st.divider()
            
            st.write("### 📄 個別應募紀錄與排行 (同步 Google 表單)")
            m_names = [m['成員名稱'] for m in members]
            tabs = st.tabs([f"{n} ({st.session_state.member_last_sales.get(n, 0)}張)" for n in m_names])
            
            for i, tab in enumerate(tabs):
                m_name = m_names[i]
                with tab:
                    log_df = st.session_state.member_logs.get(m_name, pd.DataFrame())
                    cl, cr = st.columns(2)
                    
                    with cl:
                        st.write("🕒 **歷史時間紀錄 (雲端)**")
                        if not log_df.empty:
                            st.dataframe(log_df[['時間', '張數']], use_container_width=True, hide_index=True)
                        else:
                            st.info("尚無歷史紀錄，等待數據中...")

                    with cr:
                        st.write("🏆 **單筆訂單排名**")
                        if not log_df.empty:
                            # 排名：篩選購買紀錄並由大到小排
                            rank_df = log_df[log_df['張數'] > 0][['張數']].copy()
                            if not rank_df.empty:
                                rank_df = rank_df.sort_values(by='張數', ascending=False).reset_index(drop=True)
                                rank_df.index = rank_df.index + 1
                                # 建立兩欄式表格
                                rank_display = pd.DataFrame({
                                    "排名": [f"第 {x} 名" for x in rank_df.index],
                                    "單筆訂單張數": rank_df['張數'].values
                                })
                                st.table(rank_display)
                            else:
                                st.info("尚無購買數據")

            st.write("### 📜 全體銷售異動")
            st.dataframe(st.session_state.history, use_container_width=True, hide_index=True)

    time.sleep(15)
    st.rerun()
