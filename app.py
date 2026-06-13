import streamlit as st
import sqlite3
import pandas as pd
from utils import calculate_target_price, calculate_expected_profit
from database import init_db, upsert_tracked_product
from domeme_client import DomeameClient
from notifications import send_telegram_message

# ──────────────────────────────────────────
# 기본 설정
# ──────────────────────────────────────────
st.set_page_config(
    layout="wide",
    page_title="소싱레이더 | 이커머스 마진 분석",
    page_icon="📡",
    initial_sidebar_state="expanded",
)

# ──────────────────────────────────────────
# 전문 UI 스타일 (커스텀 CSS)
# ──────────────────────────────────────────
st.markdown("""
<style>
/* 전체 배경 및 폰트 */
.block-container { padding-top: 1.2rem; padding-bottom: 2rem; max-width: 1400px; }
.stApp { background-color: #F7F8FA; }

/* 헤더 타이틀 */
.main-header {
    background: linear-gradient(135deg, #1a1a2e 0%, #16213e 50%, #0f3460 100%);
    border-radius: 16px;
    padding: 1.5rem 2rem;
    margin-bottom: 1.5rem;
    color: white;
}
.main-header h1 { font-size: 1.8rem; font-weight: 700; margin: 0; color: white; }
.main-header p  { font-size: 0.9rem; margin: 0.3rem 0 0; color: #94a3b8; }

/* KPI 카드 */
.kpi-card {
    background: white;
    border-radius: 12px;
    padding: 1.2rem 1.4rem;
    border: 1px solid #e2e8f0;
    box-shadow: 0 1px 3px rgba(0,0,0,0.06);
}
.kpi-label { font-size: 0.75rem; color: #64748b; font-weight: 600; text-transform: uppercase; letter-spacing: 0.05em; margin-bottom: 0.3rem; }
.kpi-value { font-size: 1.8rem; font-weight: 700; color: #1e293b; line-height: 1; }
.kpi-sub   { font-size: 0.75rem; color: #94a3b8; margin-top: 0.2rem; }

/* 섹션 헤더 */
.section-header {
    display: flex; align-items: center; gap: 0.5rem;
    font-size: 1rem; font-weight: 700; color: #1e293b;
    padding: 0.5rem 0; border-bottom: 2px solid #e2e8f0;
    margin-bottom: 1rem;
}

/* 검색 패널 */
.search-panel {
    background: white; border-radius: 12px;
    padding: 1.2rem 1.4rem; border: 1px solid #e2e8f0;
    box-shadow: 0 1px 3px rgba(0,0,0,0.06);
    margin-bottom: 1.2rem;
}

/* 뱃지 */
.badge-ok   { background:#dcfce7; color:#166534; padding:3px 10px; border-radius:20px; font-size:0.75rem; font-weight:600; }
.badge-oos  { background:#fee2e2; color:#991b1b; padding:3px 10px; border-radius:20px; font-size:0.75rem; font-weight:600; }
.badge-site { background:#eff6ff; color:#1d4ed8; padding:3px 10px; border-radius:20px; font-size:0.75rem; font-weight:500; }

/* 사이드바 */
section[data-testid="stSidebar"] { background: #1a1a2e !important; }
section[data-testid="stSidebar"] * { color: #cbd5e1 !important; }
section[data-testid="stSidebar"] .stSelectbox label,
section[data-testid="stSidebar"] .stSlider label { color: #94a3b8 !important; font-size:0.8rem !important; }

/* 버튼 */
.stButton > button {
    border-radius: 8px !important; font-weight: 600 !important;
    transition: all 0.2s !important;
}
.stButton > button:hover { transform: translateY(-1px); box-shadow: 0 4px 12px rgba(0,0,0,0.15) !important; }

/* 데이터 테이블 */
.stDataFrame { border-radius: 10px !important; overflow: hidden; }
.stDataFrame thead th { background: #f8fafc !important; font-weight: 600 !important; }

/* 알림 박스 */
.telegram-box {
    background: #f0fdf4; border: 1px solid #bbf7d0;
    border-radius: 10px; padding: 1rem 1.2rem; margin-top: 0.5rem;
}
.warn-box {
    background: #fefce8; border: 1px solid #fde047;
    border-radius: 10px; padding: 0.8rem 1rem; font-size: 0.85rem;
}

/* 탭 스타일 */
.stTabs [data-baseweb="tab-list"] { gap: 4px; background: #f1f5f9; border-radius: 10px; padding: 4px; }
.stTabs [data-baseweb="tab"] { border-radius: 8px !important; font-weight: 500 !important; }
.stTabs [aria-selected="true"] { background: white !important; box-shadow: 0 1px 3px rgba(0,0,0,0.1) !important; }

/* 하단 여백 */
footer { visibility: hidden; }
</style>
""", unsafe_allow_html=True)

# ──────────────────────────────────────────
# API 초기화
# ──────────────────────────────────────────
try:
    API_KEY = st.secrets["DOMEGGOOK_API_KEY"]
except Exception:
    API_KEY = ""

init_db()
client = DomeameClient(api_key=API_KEY) if API_KEY else None

# ──────────────────────────────────────────
# 상수 정의
# ──────────────────────────────────────────
CATEGORY_MAP = {
    "전체보기":      {"전체보기": "0000"},
    "패션의류":      {"전체보기": "01", "여성의류": "0101", "남성의류": "0102", "언더웨어": "0103"},
    "패션잡화":      {"전체보기": "02", "신발": "0201", "가방": "0202", "화장품/미용": "0204"},
    "디지털/가전":   {"전체보기": "04", "음향가전": "0401", "생활가전": "0402", "계절가전": "0403"},
    "생활/건강":     {"전체보기": "06", "생활용품": "0601", "건강/의료용품": "0602"},
    "식품":          {"전체보기": "09", "가공식품": "0901", "건강식품": "0902", "농축수산물": "0903"},
    "가구/인테리어": {"전체보기": "10", "가구": "1001", "인테리어소품": "1002"},
}

PLATFORM_FEE = {
    "네이버 스마트스토어": 0.08,
    "쿠팡":               0.11,
    "지마켓/옥션":        0.14,
}

MARGIN_MAP = {
    "안정형  (10%)":  0.10,
    "밸런스형 (20%)": 0.20,
    "고마진형 (40%)": 0.40,
}

PAGE_SIZE_OPTIONS = [30, 50, 100, 200]

# ──────────────────────────────────────────
# 세션 초기화
# ──────────────────────────────────────────
defaults = {
    "live_results": [], "show_results": False,
    "search_error": None, "page_num": 0,
    "sort_col": "예상 순수익(원)", "sort_asc": False,
}
for k, v in defaults.items():
    if k not in st.session_state:
        st.session_state[k] = v

# ──────────────────────────────────────────
# 헬퍼 함수
# ──────────────────────────────────────────
def fmt_krw(n):
    """원화 포맷 (1,234,567원)"""
    try:
        return f"{int(n):,}원"
    except Exception:
        return "0원"


def load_tracked_db():
    try:
        conn = sqlite3.connect("sourcing.db")
        df = pd.read_sql_query("SELECT * FROM products WHERE is_tracked = 1 ORDER BY updated_at DESC", conn)
        conn.close()
        return df if not df.empty else pd.DataFrame(
            columns=["product_id", "site", "name", "supply_price", "delivery_fee", "status", "is_tracked", "updated_at"]
        )
    except Exception as e:
        st.error(f"DB 오류: {e}")
        return pd.DataFrame()


def apply_margin(df, fee, margin):
    df = df.copy()
    df["추천 판매가(원)"] = df.apply(
        lambda r: calculate_target_price(r["supply_price"], r["delivery_fee"], fee, margin), axis=1
    )
    df["예상 순수익(원)"] = df.apply(
        lambda r: calculate_expected_profit(r["추천 판매가(원)"], r["supply_price"], r["delivery_fee"], fee), axis=1
    )
    df["마진율(%)"] = df.apply(
        lambda r: round(r["예상 순수익(원)"] / r["추천 판매가(원)"] * 100, 1) if r["추천 판매가(원)"] > 0 else 0, axis=1
    )
    return df


def do_live_search():
    st.session_state["search_error"] = None
    st.session_state["page_num"] = 0
    kw       = st.session_state.get("search_kw", "").strip()
    cat_code = CATEGORY_MAP[st.session_state["cat_main"]][st.session_state["cat_sub"]]
    site     = st.session_state.get("sourcing_site", "전체보기")
    page_sz  = st.session_state.get("page_size", 50)

    if not API_KEY:
        st.session_state["search_error"] = "API 키가 설정되지 않았습니다. Secrets를 확인하세요."
        return

    results = []
    try:
        if site in ["전체보기", "도매매"]:
            results.extend(client.fetch_product_list(
                market="supply", keyword=kw, category_code=cat_code, page_size=page_sz
            ))
        if site in ["전체보기", "도매꾹"]:
            results.extend(client.fetch_product_list(
                market="dome", keyword=kw, category_code=cat_code, page_size=page_sz
            ))
    except Exception as e:
        st.session_state["search_error"] = f"API 통신 오류: {e}"
        return

    if not results:
        st.session_state["search_error"] = "검색 결과가 없습니다. 다른 키워드나 카테고리를 시도해보세요."
    else:
        df = pd.DataFrame(results).drop_duplicates(subset=["product_id"])
        st.session_state["live_results"] = df.to_dict("records")
    st.session_state["show_results"] = True


def reset_all():
    for k in ["search_kw", "live_results", "show_results", "search_error", "page_num"]:
        st.session_state[k] = "" if k == "search_kw" else ([] if k == "live_results" else (False if k == "show_results" else None if k == "search_error" else 0))
    st.rerun()


# ──────────────────────────────────────────
# 사이드바
# ──────────────────────────────────────────
with st.sidebar:
    st.markdown("## 📡 소싱레이더")
    st.markdown("---")

    st.markdown("#### 🏪 소싱 설정")
    sourcing_site = st.selectbox("소싱 업체", ["전체보기", "도매매", "도매꾹"], key="sourcing_site")
    page_size     = st.selectbox("검색 결과 수", PAGE_SIZE_OPTIONS, index=1, key="page_size",
                                  help="한 번에 가져올 상품 수. 많을수록 API 응답이 느려집니다.")

    st.markdown("#### 💰 판매 전략")
    platform_name = st.selectbox("판매 플랫폼", list(PLATFORM_FEE.keys()))
    margin_name   = st.select_slider("마진 전략", options=list(MARGIN_MAP.keys()))

    fee    = PLATFORM_FEE[platform_name]
    margin = MARGIN_MAP[margin_name]

    st.markdown(f"""
    <div style="background:#0f3460;border-radius:10px;padding:0.8rem 1rem;margin-top:0.5rem">
        <div style="color:#94a3b8;font-size:0.72rem;font-weight:600;letter-spacing:.05em">현재 설정</div>
        <div style="color:white;font-size:1.1rem;font-weight:700;margin-top:0.2rem">
            플랫폼 수수료 {int(fee*100)}% &nbsp;|&nbsp; 목표마진 {int(margin*100)}%
        </div>
        <div style="color:#64748b;font-size:0.72rem;margin-top:0.2rem">
            최소 판매가 = (공급가+배송비) ÷ {round(1-fee-margin, 2)}
        </div>
    </div>
    """, unsafe_allow_html=True)

    st.markdown("---")

    # 관심 상품 현황
    tracked_summary = load_tracked_db()
    total_t = len(tracked_summary)
    oos_t   = len(tracked_summary[tracked_summary["status"] != "Y"]) if not tracked_summary.empty else 0
    ok_t    = total_t - oos_t

    st.markdown("#### 📊 관심 상품 현황")
    c1, c2 = st.columns(2)
    c1.metric("전체", total_t)
    c2.metric("❌ 품절", oos_t)

    st.markdown("---")

    # 텔레그램 테스트
    st.markdown("#### 📱 텔레그램 알림")
    tg_status = "✅ 연동됨" if (
        st.secrets.get("TELEGRAM_BOT_TOKEN", "") not in ["", "봇토큰_입력"] if hasattr(st, "secrets") else False
    ) else "⚠️ 미설정"
    st.markdown(f"상태: **{tg_status}**")
    if st.button("🔔 테스트 메시지 발송", use_container_width=True):
        ok = send_telegram_message("✅ [소싱레이더] 텔레그램 연동 테스트 성공!\n\n현재 관심 상품 수: {}개".format(total_t))
        if ok:
            st.success("발송 완료!")
        else:
            st.error("발송 실패. Secrets의 TELEGRAM 설정을 확인하세요.")

    st.markdown("---")
    st.caption("소싱레이더 v2.0 | 매일 04:00 자동 업데이트")


# ──────────────────────────────────────────
# 메인 헤더
# ──────────────────────────────────────────
st.markdown("""
<div class="main-header">
    <h1>📡 소싱레이더</h1>
    <p>실시간 도매 상품 마진 분석 &amp; 관심 상품 가격/재고 모니터링 시스템</p>
</div>
""", unsafe_allow_html=True)

# ──────────────────────────────────────────
# 탭 구성
# ──────────────────────────────────────────
tab_search, tab_monitor, tab_telegram, tab_guide = st.tabs([
    "🔍 라이브 검색", "⭐ 관심 상품 모니터링", "📱 텔레그램 설정", "📖 사용 가이드"
])


# ══════════════════════════════════════════
# TAB 1: 라이브 검색
# ══════════════════════════════════════════
with tab_search:

    # 검색 패널
    with st.container():
        st.markdown('<div class="search-panel">', unsafe_allow_html=True)
        col1, col2, col3 = st.columns([1.2, 1.2, 2.6])
        with col1:
            main_cat = st.selectbox("대분류", list(CATEGORY_MAP.keys()), key="cat_main", label_visibility="visible")
        with col2:
            st.selectbox("중분류", list(CATEGORY_MAP[main_cat].keys()), key="cat_sub")
        with col3:
            st.text_input("🔎 상품 키워드", key="search_kw",
                          placeholder="예: 백팩, 무선이어폰, 텀블러...",
                          on_change=do_live_search)

        btn1, btn2, btn3 = st.columns([1.5, 1, 3])
        with btn1:
            st.button("🔍 검색", on_click=do_live_search, use_container_width=True, type="primary")
        with btn2:
            st.button("🔄 초기화", on_click=reset_all, use_container_width=True)
        st.markdown('</div>', unsafe_allow_html=True)

    # 오류 표시
    if st.session_state.get("search_error"):
        st.warning(f"⚠️ {st.session_state['search_error']}")

    if not st.session_state["show_results"]:
        st.markdown("""
        <div style="text-align:center;padding:3rem 0;color:#94a3b8">
            <div style="font-size:3rem">📦</div>
            <div style="font-size:1rem;margin-top:0.5rem">위에서 카테고리와 키워드를 설정하고 검색하세요</div>
            <div style="font-size:0.85rem;margin-top:0.3rem">도매매·도매꾹 실시간 데이터로 마진을 즉시 분석합니다</div>
        </div>
        """, unsafe_allow_html=True)
    else:
        raw_df = pd.DataFrame(st.session_state["live_results"])

        if raw_df.empty:
            st.info("검색 결과가 없습니다.")
        else:
            # ── 필터 + 정렬 바 ──
            fc1, fc2, fc3, fc4 = st.columns([2, 1.2, 1.2, 1.2])
            with fc1:
                kw_filter = st.text_input("결과 내 재검색", "", placeholder="상품명 필터...", label_visibility="collapsed")
            with fc2:
                status_filter = st.selectbox("상태", ["전체", "정상만", "품절 제외"], label_visibility="collapsed")
            with fc3:
                sort_col = st.selectbox("정렬 기준",
                    ["예상 순수익(원)", "공급가(원)", "마진율(%)", "추천 판매가(원)"],
                    label_visibility="collapsed")
            with fc4:
                sort_order = st.selectbox("정렬 순서", ["높은순", "낮은순"], label_visibility="collapsed")

            # 마진 계산 적용
            df = apply_margin(raw_df, fee, margin)
            df["상태"] = df["status"].apply(lambda x: "🟢 정상" if str(x) == "Y" else "❌ 품절")

            # 필터 적용
            if kw_filter:
                df = df[df["name"].str.contains(kw_filter, case=False, na=False)]
            if status_filter == "정상만":
                df = df[df["status"] == "Y"]
            elif status_filter == "품절 제외":
                df = df[df["status"] == "Y"]

            # 정렬 적용
            df = df.sort_values(sort_col, ascending=(sort_order == "낮은순"))

            # KPI 요약
            total_cnt = len(df)
            ok_cnt    = len(df[df["status"] == "Y"])
            avg_profit= int(df[df["status"]=="Y"]["예상 순수익(원)"].mean()) if ok_cnt > 0 else 0
            max_profit= int(df["예상 순수익(원)"].max()) if total_cnt > 0 else 0

            k1, k2, k3, k4 = st.columns(4)
            k1.markdown(f'<div class="kpi-card"><div class="kpi-label">검색 결과</div><div class="kpi-value">{total_cnt}</div><div class="kpi-sub">개 상품</div></div>', unsafe_allow_html=True)
            k2.markdown(f'<div class="kpi-card"><div class="kpi-label">정상 판매 가능</div><div class="kpi-value" style="color:#16a34a">{ok_cnt}</div><div class="kpi-sub">개 상품</div></div>', unsafe_allow_html=True)
            k3.markdown(f'<div class="kpi-card"><div class="kpi-label">평균 예상 순수익</div><div class="kpi-value">{avg_profit:,}</div><div class="kpi-sub">원/건</div></div>', unsafe_allow_html=True)
            k4.markdown(f'<div class="kpi-card"><div class="kpi-label">최고 예상 순수익</div><div class="kpi-value" style="color:#2563eb">{max_profit:,}</div><div class="kpi-sub">원/건</div></div>', unsafe_allow_html=True)

            st.markdown("<br>", unsafe_allow_html=True)

            # ── 페이지네이션 ──
            page_sz   = st.session_state.get("page_size", 50)
            total_pg  = max(1, (len(df) + page_sz - 1) // page_sz)
            page_num  = min(st.session_state["page_num"], total_pg - 1)
            page_df   = df.iloc[page_num * page_sz : (page_num + 1) * page_sz].copy()

            # 관심 등록 여부
            tracked_data = load_tracked_db()
            tracked_ids  = tracked_data["product_id"].astype(str).tolist() if not tracked_data.empty else []
            page_df["⭐ 관심 등록"] = page_df["product_id"].astype(str).isin(tracked_ids)

            # 표시 컬럼
            show_cols = ["⭐ 관심 등록", "site", "product_id", "name", "supply_price", "delivery_fee",
                         "상태", "추천 판매가(원)", "예상 순수익(원)", "마진율(%)"]
            disp = page_df[show_cols].copy()
            disp.columns = ["⭐ 관심", "소싱처", "상품코드", "상품명", "공급가(원)", "배송비(원)",
                            "상태", "추천 판매가(원)", "예상 순수익(원)", "마진율(%)"]

            edited = st.data_editor(
                disp,
                use_container_width=True,
                hide_index=True,
                key=f"live_editor_{page_num}",
                column_config={
                    "⭐ 관심":        st.column_config.CheckboxColumn("⭐ 관심", width="small"),
                    "소싱처":         st.column_config.TextColumn("소싱처", width="small"),
                    "상품코드":       st.column_config.TextColumn("상품코드", width="small"),
                    "상품명":         st.column_config.TextColumn("상품명", width="large"),
                    "공급가(원)":     st.column_config.NumberColumn("공급가(원)", format="%d원"),
                    "배송비(원)":     st.column_config.NumberColumn("배송비(원)", format="%d원"),
                    "추천 판매가(원)":st.column_config.NumberColumn("추천 판매가(원)", format="%d원"),
                    "예상 순수익(원)":st.column_config.NumberColumn("예상 순수익(원)", format="%d원"),
                    "마진율(%)":      st.column_config.NumberColumn("마진율(%)", format="%.1f%%"),
                },
            )

            # 관심 등록 변경 감지
            for i in range(len(edited)):
                if edited.iloc[i]["⭐ 관심"] != disp.iloc[i]["⭐ 관심"]:
                    orig = page_df.iloc[i].to_dict()
                    upsert_tracked_product(orig, 1 if edited.iloc[i]["⭐ 관심"] else 0)
                    st.rerun()

            # 페이지 이동 버튼
            pn1, pn2, pn3 = st.columns([1, 3, 1])
            with pn1:
                if st.button("◀ 이전", disabled=(page_num == 0), use_container_width=True):
                    st.session_state["page_num"] = page_num - 1
                    st.rerun()
            with pn2:
                st.markdown(f"<div style='text-align:center;color:#64748b;font-size:0.85rem;padding-top:0.5rem'>{page_num+1} / {total_pg} 페이지 &nbsp;|&nbsp; 총 {len(df):,}개</div>", unsafe_allow_html=True)
            with pn3:
                if st.button("다음 ▶", disabled=(page_num >= total_pg - 1), use_container_width=True):
                    st.session_state["page_num"] = page_num + 1
                    st.rerun()


# ══════════════════════════════════════════
# TAB 2: 관심 상품 모니터링
# ══════════════════════════════════════════
with tab_monitor:
    tracked_df = load_tracked_db()

    if tracked_df.empty:
        st.markdown("""
        <div style="text-align:center;padding:3rem 0;color:#94a3b8">
            <div style="font-size:3rem">⭐</div>
            <div style="font-size:1rem;margin-top:0.5rem">관심 상품이 없습니다</div>
            <div style="font-size:0.85rem;margin-top:0.3rem">검색 탭에서 ⭐를 체크하면 여기에 저장됩니다</div>
        </div>
        """, unsafe_allow_html=True)
    else:
        # KPI
        total_m = len(tracked_df)
        oos_m   = len(tracked_df[tracked_df["status"] != "Y"])
        ok_m    = total_m - oos_m

        tracked_df = apply_margin(tracked_df, fee, margin)
        avg_m = int(tracked_df[tracked_df["status"]=="Y"]["예상 순수익(원)"].mean()) if ok_m > 0 else 0

        k1, k2, k3, k4 = st.columns(4)
        k1.markdown(f'<div class="kpi-card"><div class="kpi-label">관심 상품</div><div class="kpi-value">{total_m}</div><div class="kpi-sub">개</div></div>', unsafe_allow_html=True)
        k2.markdown(f'<div class="kpi-card"><div class="kpi-label">정상 판매 가능</div><div class="kpi-value" style="color:#16a34a">{ok_m}</div><div class="kpi-sub">개</div></div>', unsafe_allow_html=True)
        k3.markdown(f'<div class="kpi-card"><div class="kpi-label">❌ 품절</div><div class="kpi-value" style="color:#dc2626">{oos_m}</div><div class="kpi-sub">개</div></div>', unsafe_allow_html=True)
        k4.markdown(f'<div class="kpi-card"><div class="kpi-label">평균 예상 순수익</div><div class="kpi-value">{avg_m:,}</div><div class="kpi-sub">원/건</div></div>', unsafe_allow_html=True)

        st.markdown("<br>", unsafe_allow_html=True)

        # 모니터링 필터
        mf1, mf2 = st.columns([2, 1])
        with mf1:
            m_filter = st.text_input("상품명 검색", "", placeholder="관심 상품 내 검색...", label_visibility="collapsed")
        with mf2:
            m_status = st.selectbox("상태 필터", ["전체", "정상만", "품절만"], label_visibility="collapsed")

        mdf = tracked_df.copy()
        mdf["상태"] = mdf["status"].apply(lambda x: "🟢 정상" if str(x) == "Y" else "❌ 품절")
        if m_filter:
            mdf = mdf[mdf["name"].str.contains(m_filter, case=False, na=False)]
        if m_status == "정상만":
            mdf = mdf[mdf["status"] == "Y"]
        elif m_status == "품절만":
            mdf = mdf[mdf["status"] != "Y"]

        mdf["❌ 해제"] = True
        m_show = ["❌ 해제", "site", "product_id", "name", "supply_price", "delivery_fee",
                  "상태", "추천 판매가(원)", "예상 순수익(원)", "마진율(%)", "updated_at"]
        mdf_disp = mdf[[c for c in m_show if c in mdf.columns]].copy()
        mdf_disp.columns = ["❌ 해제", "소싱처", "상품코드", "상품명", "공급가(원)", "배송비(원)",
                            "상태", "추천 판매가(원)", "예상 순수익(원)", "마진율(%)", "최종 업데이트"][:len(mdf_disp.columns)]

        edited_m = st.data_editor(
            mdf_disp,
            column_config={
                "❌ 해제":         st.column_config.CheckboxColumn("❌ 해제", default=True, width="small"),
                "공급가(원)":      st.column_config.NumberColumn(format="%d원"),
                "배송비(원)":      st.column_config.NumberColumn(format="%d원"),
                "추천 판매가(원)": st.column_config.NumberColumn(format="%d원"),
                "예상 순수익(원)": st.column_config.NumberColumn(format="%d원"),
                "마진율(%)":       st.column_config.NumberColumn(format="%.1f%%"),
            },
            disabled=["소싱처","상품코드","상품명","공급가(원)","배송비(원)","상태","추천 판매가(원)","예상 순수익(원)","마진율(%)","최종 업데이트"],
            use_container_width=True,
            hide_index=True,
            key="tracked_editor",
        )

        changed = False
        for i in range(len(edited_m)):
            if not edited_m.iloc[i]["❌ 해제"]:
                upsert_tracked_product(mdf.iloc[i].to_dict(), 0)
                changed = True
        if changed:
            st.rerun()

        # 텔레그램으로 현황 전송
        st.markdown("<br>", unsafe_allow_html=True)
        if st.button("📱 현재 관심 상품 현황을 텔레그램으로 전송", use_container_width=True):
            lines = [f"📊 *관심 상품 현황 리포트*\n"]
            lines.append(f"전체: {total_m}개 | 정상: {ok_m}개 | 품절: {oos_m}개\n")
            for _, row in tracked_df.iterrows():
                icon = "🟢" if row["status"] == "Y" else "❌"
                lines.append(f"{icon} {row['name'][:25]} — 판매가 {int(row['추천 판매가(원)']):,}원 / 수익 {int(row['예상 순수익(원)']):,}원")
            send_telegram_message("\n".join(lines))
            st.success("텔레그램으로 전송했습니다!")


# ══════════════════════════════════════════
# TAB 3: 텔레그램 설정 가이드
# ══════════════════════════════════════════
with tab_telegram:
    st.markdown("### 📱 텔레그램 알림 설정")

    col_a, col_b = st.columns(2)

    with col_a:
        st.markdown("""
        #### 1단계 — 봇 만들기
        1. 텔레그램 앱에서 **@BotFather** 검색
        2. `/newbot` 입력
        3. 봇 이름 입력 (예: `소싱레이더봇`)
        4. 봇 username 입력 (예: `sourcing_radar_bot`)
        5. 발급된 **토큰** 복사 (예: `7123456789:AAF...`)

        #### 2단계 — 채팅방 ID 확인
        1. 만든 봇에게 아무 메시지 전송
        2. 브라우저에서 아래 주소 접속:
        ```
        https://api.telegram.org/bot[토큰]/getUpdates
        ```
        3. `"chat":{"id":` 뒤의 숫자가 채팅방 ID
        """)

    with col_b:
        st.markdown("""
        #### 3단계 — Streamlit Secrets에 등록
        share.streamlit.io → 내 앱 → Settings → Secrets
        """)
        st.code("""DOMEGGOOK_API_KEY = "여기에_API_키"
TELEGRAM_BOT_TOKEN = "여기에_봇_토큰"
TELEGRAM_CHAT_ID   = "여기에_채팅방_ID"
""", language="toml")

        st.markdown("#### 4단계 — 연동 테스트")
        test_msg = st.text_input("테스트 메시지", value="안녕하세요! 소싱레이더 텔레그램 연동 테스트입니다 ✅")
        if st.button("📤 테스트 발송", type="primary", use_container_width=True):
            ok = send_telegram_message(test_msg)
            if ok:
                st.success("✅ 발송 성공! 텔레그램을 확인하세요.")
            else:
                st.error("❌ 발송 실패. 토큰과 채팅방 ID를 다시 확인하세요.")

    st.markdown("---")
    st.markdown("""
    #### 📅 자동 알림 시나리오
    | 상황 | 알림 내용 |
    |------|----------|
    | 매일 새벽 4시 | 관심 상품 전체 상태 점검 리포트 |
    | 품절 전환 | ❌ 즉시 품절 알림 |
    | 공급가 인상 | 🔴 인상 전/후 가격 비교 알림 |
    | 배치 완료 | ✅ 점검 완료 요약 |
    """)


# ══════════════════════════════════════════
# TAB 4: 사용 가이드
# ══════════════════════════════════════════
with tab_guide:
    st.markdown("### 📖 소싱레이더 사용 가이드")

    with st.expander("💡 마진 계산 공식 이해하기", expanded=True):
        st.markdown("""
        **추천 판매가 공식:**
        ```
        추천 판매가 = (공급가 + 배송비) ÷ (1 - 플랫폼수수료율 - 목표마진율)
        ```
        **예시 (네이버 8% | 밸런스형 20%):**
        - 공급가 10,000원 + 배송비 3,000원 = 원가 13,000원
        - 추천 판매가 = 13,000 ÷ (1 - 0.08 - 0.20) = **18,056원 → 18,060원**
        - 예상 순수익 = 18,060 - (18,060 × 0.08) - 10,000 - 3,000 = **3,612원**
        """)

    with st.expander("🔍 검색 결과 수 설정"):
        st.markdown("""
        왼쪽 사이드바 **'검색 결과 수'** 에서 30 / 50 / 100 / 200개를 선택할 수 있습니다.
        - **30~50개**: 빠른 탐색용 (응답 1~2초)
        - **100개**: 일반 소싱 분석 (응답 3~5초)
        - **200개**: 대량 비교 분석 (응답 5~10초, API 제한에 따라 실제 수량이 다를 수 있음)
        """)

    with st.expander("⭐ 관심 상품 등록 및 모니터링"):
        st.markdown("""
        1. 검색 결과 표에서 원하는 상품의 **⭐ 관심** 체크박스 클릭
        2. **관심 상품 모니터링 탭**에서 등록된 상품 한눈에 확인
        3. 매일 새벽 4시 자동 상태 점검 후 변동 시 텔레그램 알림 발송
        4. ❌ 해제 체크박스를 해제하면 모니터링 목록에서 제거
        """)

    with st.expander("📱 텔레그램 알림 활용법"):
        st.markdown("""
        - **자동 알림**: 매일 새벽 4시 배치 실행 후 변동 상품 자동 보고
        - **수동 전송**: 관심 상품 탭 하단 버튼으로 현황 즉시 전송
        - **테스트**: 텔레그램 설정 탭에서 연동 상태 확인 및 테스트 메시지 발송
        """)
