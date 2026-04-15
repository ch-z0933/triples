import streamlit as st
import requests
import pandas as pd
import time
from datetime import datetime
import pytz
import gspread
from google.oauth2.service_account import Credentials

# =========================
# 1. Google Sheets 連線
# =========================
def init_connection():
    scope = [
        "https://www.googleapis.com/auth/spreadsheets",
        "https://www.googleapis.com/auth/drive"
    ]
    creds_dict = dict(st.secrets["gcp_service_account"])
    creds = Credentials.from_service_account_info(creds_dict, scopes=scope)
    client = gspread.authorize(creds)
    return client.open("tripleS_Neptune_Sales")

try:
    gc = init_connection()
except Exception as e:
    st.error(f"雲端連線失敗: {e}")
    gc = None

# =========================
# 2. 頁面設定
# =========================
st.set_page_config(page_title="tripleS Neptune 特別合照監控", layout="wide")
st.title("🌌 tripleS 合照活動 in Taipei")

TW_API = "https://www.kmonstar.com.tw/products/%E6%87%89%E5%8B%9F-260425-triples-neptune-sss-summit-in-asia-11-%E7%89%B9%E5%88%A5%E5%90%88%E7%85%A7%E6%B4%BB%E5%8B%95-in-taipei.json"

# 你這場的 6 位成員
TARGET_MEMBERS = [
    "서연 SeoYeon",
    "나경 NaKyoung",
    "다현 DaHyun",
    "코토네 Kotone",
    "니엔 Nien",
    "서아 SeoAh",
]

# Google Sheet 統一欄位
LOG_COLUMNS = ['時間', '張數', '來源', '總銷售量']

# =========================
# 3. 初始化 session_state
# =========================
if 'member_logs' not in st.session_state:
    st.session_state.member_logs = {}

if 'last_totals' not in st.session_state:
    st.session_state.last_totals = {}

if 'last_raw_sales' not in st.session_state:
    st.session_state.last_raw_sales = {}

# =========================
# 4. Google Sheet 同步
# =========================
def ensure_worksheet(name):
    """確保每位成員都有自己的 worksheet，沒有就建立。"""
    if not gc:
        return None

    try:
        return gc.worksheet(name)
    except:
        try:
            wks = gc.add_worksheet(title=name, rows=1000, cols=10)
            wks.append_row(LOG_COLUMNS)
            return wks
        except Exception as e:
            st.sidebar.error(f"建立工作表 {name} 失敗: {e}")
            return None

def sync_from_cloud(names):
    """從 Google Sheet 把現有資料同步到 session_state。"""
    if not gc:
        for name in names:
            if name not in st.session_state.member_logs:
                st.session_state.member_logs[name] = pd.DataFrame(columns=LOG_COLUMNS)
        return

    for name in names:
        if name not in st.session_state.member_logs or st.session_state.member_logs[name].empty:
            try:
                wks = ensure_worksheet(name)
                if wks is None:
                    st.session_state.member_logs[name] = pd.DataFrame(columns=LOG_COLUMNS)
                    continue

                values = wks.get_all_values()

                if not values:
                    st.session_state.member_logs[name] = pd.DataFrame(columns=LOG_COLUMNS)
                    continue

                # 若第一列不是正確標題，補上標題
                if values[0] != LOG_COLUMNS:
                    wks.clear()
                    wks.append_row(LOG_COLUMNS)
                    st.session_state.member_logs[name] = pd.DataFrame(columns=LOG_COLUMNS)
                    continue

                if len(values) == 1:
                    st.session_state.member_logs[name] = pd.DataFrame(columns=LOG_COLUMNS)
                    continue

                df = pd.DataFrame(values[1:], columns=values[0])
                df['張數'] = pd.to_numeric(df['張數'], errors='coerce').fillna(0).astype(int)
                df['總銷售量'] = pd.to_numeric(df['總銷售量'], errors='coerce').fillna(0).astype(int)

                # 最新一筆放最上面
                df = df.iloc[::-1].reset_index(drop=True)
                st.session_state.member_logs[name] = df

            except Exception as e:
                st.sidebar.error(f"同步 {name} 失敗: {e}")
                st.session_state.member_logs[name] = pd.DataFrame(columns=LOG_COLUMNS)

# =========================
# 5. 抓 API
# =========================
def get_tw_data():
    tw_data = {}

    headers = {
        "User-Agent": "Mozilla/5.0",
        "Accept": "application/json",
        "Referer": "https://www.kmonstar.com.tw/"
    }

    try:
        res = requests.get(
            f"{TW_API}?t={int(time.time())}",
            headers=headers,
            timeout=10
        )
        res.raise_for_status()
        data = res.json()

        for v in data.get("variants", []):
            name = (v.get("option1") or "").strip()
            if name in TARGET_MEMBERS:
                inventory_qty = v.get("inventory_quantity", 0)

                # 這站目前是用 inventory_quantity 反映銷售累積
                # 常見情況是負數，所以用 abs() 轉成累積銷量
                sold = abs(int(inventory_qty))
                tw_data[name] = tw_data.get(name, 0) + sold

    except Exception as e:
        st.sidebar.error(f"台灣 API 抓取失敗: {e}")

    # 確保 6 位都存在
    for member in TARGET_MEMBERS:
        tw_data.setdefault(member, 0)

    return tw_data

# =========================
# 6. 寫入 Google Sheet
# =========================
def append_sale_log(name, now_str, diff, source, total_now):
    if not gc:
        return False

    try:
        wks = ensure_worksheet(name)
        if wks is None:
            return False

        wks.append_row([now_str, int(diff), source, int(total_now)])
        return True
    except Exception as e:
        st.sidebar.error(f"寫入 {name} 失敗: {e}")
        return False

# =========================
# 7. 主監控
# =========================
status_placeholder = st.empty()

tw_res = get_tw_data()
all_names = sorted(TARGET_MEMBERS)
sync_from_cloud(all_names)

tz = pytz.timezone('Asia/Taipei')
now = datetime.now(tz).strftime("%Y-%m-%d %H:%M:%S")

for name in all_names:
    total_now = int(tw_res.get(name, 0))
    log_df = st.session_state.member_logs.get(name, pd.DataFrame(columns=LOG_COLUMNS))

    last_total_in_sheet = 0
    if not log_df.empty and '總銷售量' in log_df.columns:
        last_total_in_sheet = int(pd.to_numeric(
            pd.Series([log_df.iloc[0]['總銷售量']]),
            errors='coerce'
        ).fillna(0).iloc[0])

    diff = total_now - last_total_in_sheet

    # 只有增加時才寫入
    if diff > 0:
        source = "tw"
        ok = append_sale_log(name, now, diff, source, total_now)

        if ok:
            new_entry = pd.DataFrame([{
                '時間': now,
                '張數': int(diff),
                '來源': source,
                '總銷售量': int(total_now)
            }])

            st.session_state.member_logs[name] = pd.concat(
                [new_entry, log_df],
                ignore_index=True
            )

    st.session_state.last_totals[name] = total_now

# =========================
# 8. 畫面顯示
# =========================
with status_placeholder.container():
    st.write("### 👥 6位成員總銷量統計")

    summary = []
    for n in all_names:
        total = int(tw_res.get(n, 0))
        summary.append({
            "成員名稱": n,
            "總銷量": total
        })

    summary_df = pd.DataFrame(summary).sort_values("總銷量", ascending=False).reset_index(drop=True)
    st.table(summary_df)

    st.divider()

    tabs = st.tabs(all_names)
    for i, tab in enumerate(tabs):
        m_name = all_names[i]
        with tab:
            log_df = st.session_state.member_logs.get(m_name, pd.DataFrame(columns=LOG_COLUMNS))

            cl, cr = st.columns(2)

            with cl:
                st.write("🕒 **銷售時間紀錄**")
                if not log_df.empty:
                    st.dataframe(
                        log_df[['時間', '張數', '來源']],
                        use_container_width=True,
                        hide_index=True
                    )
                else:
                    st.info("目前沒有紀錄")

            with cr:
                st.write("🏆 **單筆排行**")
                if not log_df.empty:
                    rank_df = log_df.copy()
                    rank_df['張數'] = pd.to_numeric(rank_df['張數'], errors='coerce').fillna(0).astype(int)
                    rank_df = rank_df[rank_df['張數'] > 0]

                    if not rank_df.empty:
                        rank_df = rank_df.sort_values("張數", ascending=False).reset_index(drop=True)
                        rank_df.index = rank_df.index + 1

                        rank_display = pd.DataFrame({
                            "排名": [f"第 {idx} 名" for idx in rank_df.index],
                            "單筆張數": rank_df['張數'].values,
                            "來源": rank_df['來源'].values
                        })
                        st.table(rank_display)
                    else:
                        st.info("目前沒有正向變動紀錄")
                else:
                    st.info("目前沒有排行資料")

st.caption(f"最後更新時間：{now}")
time.sleep(15)
st.rerun()
