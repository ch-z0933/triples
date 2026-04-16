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
INTL_API = "https://kmonstar.com/api/v1/event/detail/73b8ed0c-742e-4543-ba0c-4101b4ec6102"

TARGET_MEMBERS = [
    "서연 SeoYeon",
    "나경 NaKyoung",
    "다현 DaHyun",
    "코토네 Kotone",
    "니엔 Nien",
    "서아 SeoAh",
]

# 國際版名稱對應到台灣版名稱
NAME_MAP = {
    "SeoYeon": "서연 SeoYeon",
    "NaKyoung": "나경 NaKyoung",
    "DaHyun": "다현 DaHyun",
    "Kotone": "코토네 Kotone",
    "Nien": "니엔 Nien",
    "SeoAh": "서아 SeoAh",
    "Seo Ah": "서아 SeoAh",
    "Na Kyoung": "나경 NaKyoung",
}

LOG_COLUMNS = ['時間', '張數', '來源', '總銷售量']

# =========================
# 3. 初始化 session_state
# =========================
if 'member_logs' not in st.session_state:
    st.session_state.member_logs = {}

if 'last_totals' not in st.session_state:
    st.session_state.last_totals = {}

if 'last_tw_totals' not in st.session_state:
    st.session_state.last_tw_totals = {}

if 'last_intl_totals' not in st.session_state:
    st.session_state.last_intl_totals = {}

if 'bootstrapped' not in st.session_state:
    st.session_state.bootstrapped = False

# =========================
# 4. Google Sheet 同步
# =========================
def ensure_worksheet(name):
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

                df = df.iloc[::-1].reset_index(drop=True)
                st.session_state.member_logs[name] = df

            except Exception as e:
                st.sidebar.error(f"同步 {name} 失敗: {e}")
                st.session_state.member_logs[name] = pd.DataFrame(columns=LOG_COLUMNS)

# =========================
# 5. API 抓取
# =========================
def get_tw_data(session):
    tw_data = {}

    headers = {
        "User-Agent": "Mozilla/5.0",
        "Accept": "application/json",
        "Referer": "https://www.kmonstar.com.tw/"
    }

    try:
        res = session.get(
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
                sold = abs(int(inventory_qty))
                tw_data[name] = tw_data.get(name, 0) + sold

    except Exception as e:
        st.sidebar.error(f"台灣 API 抓取失敗: {e}")

    for member in TARGET_MEMBERS:
        tw_data.setdefault(member, 0)

    return tw_data

def get_intl_data(session):
    intl_data = {}

    headers = {
        "User-Agent": "Mozilla/5.0",
        "Accept": "application/json, text/plain, */*",
        "Referer": "https://kmonstar.com/zh/eventproductdetail/73b8ed0c-742e-4543-ba0c-4101b4ec6102",
        "Origin": "https://kmonstar.com",
    }

    try:
        res = session.get(
            f"{INTL_API}?t={int(time.time())}",
            headers=headers,
            timeout=10
        )

        if res.status_code == 200:
            data = res.json()
            options = data.get("data", {}).get("optionList", [])

            for o in options:
                name = (o.get("optionNameValue1") or "").strip()

                # 🔥 核心：用 stockKo 算銷量
                stock_ko = o.get("stockKo", {}).get("quantity")

                if stock_ko is not None:
                    sold = 1000 - int(stock_ko)   # ← 初始 1000

                    if name in TARGET_MEMBERS:
                        intl_data[name] = sold

        else:
            st.write(f"INTL failed: {res.status_code}")

    except Exception as e:
        st.write(f"INTL exception: {e}")

    for member in TARGET_MEMBERS:
        intl_data.setdefault(member, 0)

    return intl_data

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
# 7. 主流程
# =========================
status_placeholder = st.empty()

session = requests.Session()

tw_res = get_tw_data(session)
intl_res = get_intl_data(session)

# 🔥 加在這裡（就在 API 抓完後）
st.write("==== DEBUG INTL ====")
st.write(intl_res)

all_names = TARGET_MEMBERS.copy()
sync_from_cloud(all_names)

tz = pytz.timezone('Asia/Taipei')
now = datetime.now(tz).strftime("%Y-%m-%d %H:%M:%S")

for name in all_names:
    tw_now = int(tw_res.get(name, 0))
    intl_now = int(intl_res.get(name, 0))
    total_now = tw_now + intl_now

    log_df = st.session_state.member_logs.get(name, pd.DataFrame(columns=LOG_COLUMNS))

    last_total_in_sheet = 0
    if not log_df.empty and '總銷售量' in log_df.columns:
        last_total_in_sheet = int(pd.to_numeric(
            pd.Series([log_df.iloc[0]['總銷售量']]),
            errors='coerce'
        ).fillna(0).iloc[0])

    diff = total_now - last_total_in_sheet

    # 第一次啟動且 sheet 為空時，不補舊單，只建立基準
    if not st.session_state.bootstrapped and last_total_in_sheet == 0:
        st.session_state.last_totals[name] = total_now
        st.session_state.last_tw_totals[name] = tw_now
        st.session_state.last_intl_totals[name] = intl_now
        continue

    if diff > 0:
        source_parts = []
        prev_tw = st.session_state.last_tw_totals.get(name, tw_now)
        prev_intl = st.session_state.last_intl_totals.get(name, intl_now)

        if tw_now > prev_tw:
            source_parts.append(f"TW+{tw_now - prev_tw}")
        if intl_now > prev_intl:
            source_parts.append(f"INTL+{intl_now - prev_intl}")

        source = " / ".join(source_parts) if source_parts else "合計變動"

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
    st.session_state.last_tw_totals[name] = tw_now
    st.session_state.last_intl_totals[name] = intl_now

st.session_state.bootstrapped = True

# =========================
# 8. 畫面顯示
# =========================
with status_placeholder.container():
    st.write("### 👥 6位成員總銷量統計")

    summary = []
    for n in all_names:
        tw = int(tw_res.get(n, 0))
        intl = int(intl_res.get(n, 0))
        total = tw + intl

        summary.append({
            "成員名稱": n,
            "台灣版": tw,
            "國際版": intl,
            "總計": total
        })

    summary_df = pd.DataFrame(summary).sort_values("總計", ascending=False).reset_index(drop=True)
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
