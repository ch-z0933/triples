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
    # 請確保 st.secrets 中有 gcp_service_account 設定
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
st.set_page_config(page_title="tripleS Neptune 台北應募監控", layout="wide")
st.title("🌌 tripleS Neptune SSS SUMMIT 台北站")
st.caption("監控目標：KMONSTAR 台灣官網 (6位成員合照活動)")

# 這是你提供的 API 連結
TW_API = "https://www.kmonstar.com.tw/products/%E6%87%89%E5%8B%9F-260425-triples-neptune-sss-summit-in-asia-11-%E7%89%B9%E5%88%A5%E4%B8%80%E5%B0%8D%E4%B8%80%E5%92%95-objekt-%E6%B4%BB%E5%8B%95-in-taipei.json"

# --- 3. 初始化資料 ---
if 'member_logs' not in st.session_state:
    st.session_state.member_logs = {}
if 'last_total_sales' not in st.session_state:
    # 用來記錄上一次偵測到的「銷量」數值
    st.session_state.last_total_sales = {}

def sync_from_cloud(names):
    if gc:
        for name in names:
            clean_name = name.strip()
            if clean_name not in st.session_state.member_logs or st.session_state.member_logs[clean_name].empty:
                try:
                    wks = gc.worksheet(clean_name)
                    data = wks.get_all_records()
                    if data:
                        df = pd.DataFrame(data)
                        df['張數'] = pd.to_numeric(df['張數'], errors='coerce').fillna(0)
                        st.session_state.member_logs[clean_name] = df.sort_index(ascending=False)
                    else:
                        st.session_state.member_logs[clean_name] = pd.DataFrame(columns=['時間', '張數', '來源', '總銷售量'])
                except:
                    # 若工作表不存在則建立 (可選)
                    st.session_state.member_logs[clean_name] = pd.DataFrame(columns=['時間', '張數', '來源', '總銷售量'])

def get_kmonstar_data():
    """抓取 KMONSTAR 庫存並轉換為銷量數據"""
    sales_data = {}
    HEADERS = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
    }
    try:
        # 加入時間戳防止快取
        res = requests.get(f"{TW_API}?t={int(time.time())}", headers=HEADERS, timeout=10)
        if res.status_code == 200:
            product_json = res.json().get('product', {})
            variants = product_json.get('variants', [])
            
            for v in variants:
                member_name = v.get('option1') # 通常是成員名字
                # Shopify 庫存邏輯：
                # 如果庫存是設為 100 往下扣，則銷量 = 初始值 - 當前值
                # 這裡我們先取庫存的絕對值作為「觀察值」，或直接監控其變動
                current_inv = v.get('inventory_quantity', 0)
                
                # 假設：銷量計算方式為我們監控它的「減少量」
                # 為了方便統計，這裡存入的是「當前庫存的負值反轉」或是直接存庫存
                # 建議：這裡先回傳原始庫存，邏輯在主迴圈處理
                if member_name:
                    sales_data[member_name] = current_inv
            return sales_data
    except Exception as e:
        st.sidebar.error(f"API 抓取失敗: {e}")
    return None

# --- 4. 主程式執行 ---
status_placeholder = st.empty()

while True:
    current_inventory = get_kmonstar_data()
    
    if current_inventory:
        all_names = list(current_inventory.keys())
        sync_from_cloud(all_names)
        
        tz = pytz.timezone('Asia/Taipei')
        now = datetime.now(tz).strftime("%H:%M:%S")
        
        for name in all_names:
            clean_name = name.strip()
            # 這裡的 current_inv 是 API 抓到的最新剩餘庫存
            curr_inv = current_inventory[name]
            
            # 從 session 或雲端取得上一次記錄的庫存量
            log_df = st.session_state.member_logs.get(clean_name, pd.DataFrame())
            
            # 初始化：如果這是第一次執行，記下當前庫存但不算變動
            if clean_name not in st.session_state.last_total_sales:
                st.session_state.last_total_sales[clean_name] = curr_inv
                continue
            
            prev_inv = st.session_state.last_total_sales[clean_name]
            
            # 計算銷量變動：如果庫存減少了，代表賣出了
            # 變動量 = 舊庫存 - 新庫存
            diff = prev_inv - curr_inv
            
            if diff > 0:
                # 取得目前總銷量累計 (從 Sheet 最後一列拿)
                last_total_in_sheet = 0
                if not log_df.empty:
                    last_total_in_sheet = log_df.iloc[0]['總銷售量']
                
                new_total = last_total_in_sheet + diff
                source = "官網訂單"
                
                if gc:
                    try:
                        wks = gc.worksheet(clean_name)
                        wks.append_row([now, int(diff), source, int(new_total)])
                        
                        # 更新本地顯示
                        new_entry = pd.DataFrame([{'時間': now, '張數': int(diff), '來源': source, '總銷售量': int(new_total)}])
                        st.session_state.member_logs[clean_name] = pd.concat([new_entry, log_df], ignore_index=True)
                        
                        # 更新基準點
                        st.session_state.last_total_sales[clean_name] = curr_inv
                    except Exception as e:
                        st.sidebar.error(f"寫入 {clean_name} 失敗: {e}")
            
            # 若庫存增加（補貨），則更新基準點但不計入銷量
            elif diff < 0:
                st.session_state.last_total_sales[clean_name] = curr_inv

        # --- 5. 畫面渲染 ---
        with status_placeholder.container():
            st.write(f"最後更新時間: {now} (每 15 秒自動刷新)")
            
            # 彙總表格
            summary = []
            for n in all_names:
                total_s = 0
                m_df = st.session_state.member_logs.get(n, pd.DataFrame())
                if not m_df.empty:
                    total_s = m_df.iloc[0]['總銷售量']
                
                summary.append({
                    "成員": n, 
                    "目前剩餘庫存": current_inventory[n], 
                    "累計銷量": total_s
                })
            
            st.table(pd.DataFrame(summary).sort_values("累計銷量", ascending=False))

            st.divider()
            
            # 分頁顯示明細
            tabs = st.tabs(all_names)
            for i, tab in enumerate(tabs):
                m_name = all_names[i]
                with tab:
                    log_df = st.session_state.member_logs.get(m_name, pd.DataFrame())
                    if not log_df.empty:
                        st.dataframe(log_df[['時間', '張數', '來源', '總銷售量']], use_container_width=True, hide_index=True)
                    else:
                        st.info("尚無銷售紀錄")

    time.sleep(15)
    st.rerun()
