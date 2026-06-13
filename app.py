import streamlit as st
import sqlite3
import pandas as pd
from utils import calculate_target_price, calculate_expected_profit
from database import init_db, upsert_tracked_product
from domeme_client import DomeameClient
from notifications import send_telegram_message

# 온채널 클라이언트 (선택적 임포트 — beautifulsoup4 없으면 비활성)
try:
    from onchannel_client import OnchannelClient
    ONCHANNEL_AVAILABLE = True
except ImportError:
    ONCHANNEL_AVAILABLE = False

# ──────────────────────────────────────────
# 기본 설정
# ──────────────────────────────────────────
st.set_page_config(
    layout="wide",
    page_title="소싱레이더 | 이커머스 마진 분석",
    page_icon="📡",
    initial_sidebar_state="expanded",
)

st.markdown("""
<style>
.block-container { padding-top: 1.2rem; padding-bottom: 2rem; max-width: 1400px; }
.stApp { background-color: #F7F8FA; }
.main-header {
    background: linear-gradient(135deg, #1a1a2e 0%, #16213e 50%, #0f3460 100%);
    border-radius: 16px; padding: 1.5rem 2rem; margin-bottom: 1.5rem; color: white;
}
.main-header h1 { font-size: 1.8rem; font-weight: 700; margin: 0; color: white; }
.main-header p  { font-size: 0.9rem; margin: 0.3rem 0 0; color: #94a3b8; }
.kpi-card {
    background: white; border-radius: 12px; padding: 1.2rem 1.4rem;
    border: 1px solid #e2e8f0; box-shadow: 0 1px 3px rgba(0,0,0,0.06);
}
.kpi-label { font-size: 0.75rem; color: #64748b; font-weight: 600;
    text-transform: uppercase; letter-spacing: 0.05em; margin-bottom: 0.3rem; }
.kpi-value { font-size: 1.8rem; font-weight: 700; color: #1e293b; line-height: 1; }
.kpi-sub   { font-size: 0.75rem; color: #94a3b8; margin-top: 0.2rem; }
section[data-testid="stSidebar"] { background: #1a1a2e !important; }
section[data-testid="stSidebar"] * { color: #cbd5e1 !important; }
.stButton > button {
    border-radius: 8px !important; font-weight: 600 !important; transition: all 0.2s !important;
}
.stButton > button:hover { transform: translateY(-1px); box-shadow: 0 4px 12px rgba(0,0,0,0.15) !important; }
.stTabs [data-baseweb="tab-list"] { gap: 4px; background: #f1f5f9; border-radius: 10px; padding: 4px; }
.stTabs [data-baseweb="tab"] { border-radius: 8px !important; font-weight: 500 !important; }
.stTabs [aria-selected="true"] { background: white !important; box-shadow: 0 1px 3px rgba(0,0,0,0.1) !important; }
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
client    = DomeameClient(api_key=API_KEY) if API_KEY else None
oc_client = OnchannelClient() if ONCHANNEL_AVAILABLE else None

# ──────────────────────────────────────────
# 상수
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
PLATFORM_FEE = {"네이버 스마트스토어": 0.08, "쿠팡": 0.11, "지마켓/옥션": 0.14}
MARGIN_MAP   = {"안정형  (10%)": 0.10, "밸런스형 (20%)": 0.20, "고마진형 (40%)": 0.40}

# 페이지당 상품 수 × 최대 페이지 수 = 총 결과 수
FETCH_PRESETS = {
    "빠른 탐색  (50개)":   (50, 1),
    "일반 검색  (100개)":  (50, 2),
    "심층 분석  (200개)":  (50, 4),
    "대량 수집  (500개)":  (50, 10),
}

# ──────────────────────────────────────────
# 세션 초기화
# ──────────────────────────────────────────
for k, v in {
    "live_results": [], "show_results": False,
    "search_error": None, "page_num": 0,
}.items():
    if k not in st.session_state:
        st.session_state[k] = v

# ──────────────────────────────────────────
# 헬퍼
# ──────────────────────────────────────────
def load_tracked_db():
    try:
        conn = sqlite3.connect("sourcing.db")
        df   = pd.read_sql_query(
            "SELECT * FROM products WHERE is_tracked = 1 ORDER BY updated_at DESC", conn
        )
        conn.close()
        return df if not df.empty else pd.DataFrame(
            columns=["product_id","site","name","supply_price","delivery_fee","status","is_tracked","updated_at"]
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
        lambda r: round(r["예상 순수익(원)"] / r["추천 판매가(원)"] * 100, 1)
        if r["추천 판매가(원)"] > 0 else 0, axis=1
    )
    return df


def do_live_search():
    st.session_state["search_error"] = None
    st.session_state["page_num"]     = 0
    st.session_state["live_results"] = []
    st.session_state["show_results"] = False

    kw       = st.session_state.get("search_kw", "").strip()
    cat_code = CATEGORY_MAP[st.session_state["cat_main"]][st.session_state["cat_sub"]]
    sites    = st.session_state.get("sourcing_sites", ["도매매", "도매꾹"])
    preset   = st.session_state.get("fetch_preset", "일반 검색  (100개)")
    pg_size, max_pg = FETCH_PRESETS[preset]

    results = []

    # ── 도매매 / 도매꾹 ──
    if not API_KEY and any(s in sites for s in ["도매매", "도매꾹"]):
        st.session_state["search_error"] = "도매매/도매꾹 API 키가 없습니다. Secrets를 확인하세요."
    else:
        try:
            if client:
                if "도매매" in sites:
                    results.extend(client.fetch_product_list(
                        market="supply", keyword=kw, category_code=cat_code,
                        page_size=pg_size, max_pages=max_pg,
                    ))
                if "도매꾹" in sites:
                    results.extend(client.fetch_product_list(
                        market="dome", keyword=kw, category_code=cat_code,
                        page_size=pg_size, max_pages=max_pg,
                    ))
        except Exception as e:
            st.session_state["search_error"] = f"도매매/도매꾹 API 오류: {e}"

    # ── 온채널 ──
    if "온채널" in sites:
        if not ONCHANNEL_AVAILABLE:
            st.session_state["search_error"] = (
                (st.session_state["search_error"] or "") +
                " | 온채널: beautifulsoup4 라이브러리가 필요합니다."
            )
        elif oc_client and kw:
            try:
                oc_results = oc_client.fetch_product_list(
                    keyword=kw, page_size=pg_size * max_pg, max_pages=max_pg,
                )
                results.extend(oc_results)
                print(f"[온채널] 총 {len(oc_results)}개 수집")
            except Exception as e:
                st.session_state["search_error"] = (
                    (st.session_state["search_error"] or "") + f" | 온채널 오류: {e}"
                )

    if not results:
        if not st.session_state["search_error"]:
            st.session_state["search_error"] = "검색 결과가 없습니다."
    else:
        df = pd.DataFrame(results).drop_duplicates(subset=["product_id"])
        st.session_state["live_results"] = df.to_dict("records")

    st.session_state["show_results"] = True


def reset_all():
    st.session_state.update({
        "search_kw": "", "live_results": [],
        "show_results": False, "search_error": None, "page_num": 0,
    })
    st.rerun()


# ──────────────────────────────────────────
# 사이드바
# ──────────────────────────────────────────
with st.sidebar:
    st.markdown("## 📡 소싱레이더")
    st.markdown("---")

    st.markdown("#### 🏪 소싱 설정")

    # ★ 멀티셀렉트로 여러 소싱처 동시 선택
    site_options = ["도매매", "도매꾹"]
    if ONCHANNEL_AVAILABLE:
        site_options.append("온채널")

    sourcing_sites = st.multiselect(
        "소싱 업체 (복수 선택 가능)",
        options=site_options,
        default=["도매매", "도매꾹"],
        key="sourcing_sites",
    )

    fetch_preset = st.selectbox(
        "검색 수량",
        list(FETCH_PRESETS.keys()),
        index=1,
        key="fetch_preset",
        help="많을수록 정확하지만 느림 (대량 수집은 5~15초 소요)",
    )

    st.markdown("#### 💰 판매 전략")
    platform_name = st.selectbox("판매 플랫폼", list(PLATFORM_FEE.keys()))
    margin_name   = st.select_slider("마진 전략", options=list(MARGIN_MAP.keys()))

    fee    = PLATFORM_FEE[platform_name]
    margin = MARGIN_MAP[margin_name]

    st.markdown(f"""
    <div style="background:#0f3460;border-radius:10px;padding:0.8rem 1rem;margin-top:0.5rem">
        <div style="color:#94a3b8;font-size:0.72rem;font-weight:600;letter-spacing:.05em">현재 설정</div>
        <div style="color:white;font-size:1rem;font-weight:700;margin-top:0.2rem">
            수수료 {int(fee*100)}% | 목표마진 {int(margin*100)}%
        </div>
        <div style="color:#64748b;font-size:0.72rem;margin-top:0.2rem">
            최소 판매가 배수 = ÷{round(1-fee-margin, 2)}
        </div>
    </div>
    """, unsafe_allow_html=True)

    st.markdown("---")

    # 관심 상품 현황
    tracked_summary = load_tracked_db()
    total_t = len(tracked_summary)
    oos_t   = len(tracked_summary[tracked_summary["status"] != "Y"]) if not tracked_summary.empty else 0

    st.markdown("#### 📊 관심 상품")
    c1, c2 = st.columns(2)
    c1.metric("전체", total_t)
    c2.metric("❌ 품절", oos_t)

    st.markdown("---")

    st.markdown("#### 📱 텔레그램")
    try:
        tg_ok = st.secrets.get("TELEGRAM_BOT_TOKEN", "") not in ["", "봇토큰_입력"]
    except Exception:
        tg_ok = False
    st.markdown(f"상태: {'✅ 연동됨' if tg_ok else '⚠️ 미설정'}")
    if st.button("🔔 테스트 발송", use_container_width=True):
        ok = send_telegram_message(f"✅ 소싱레이더 연동 테스트!\n관심 상품: {total_t}개")
        st.success("발송 완료!") if ok else st.error("발송 실패")

    st.markdown("---")
    st.caption("소싱레이더 v3.0 | 도매매·도매꾹·온채널")


# ──────────────────────────────────────────
# 메인 헤더
# ──────────────────────────────────────────
st.markdown("""
<div class="main-header">
    <h1>📡 소싱레이더</h1>
    <p>도매매 · 도매꾹 · 온채널 실시간 통합 마진 분석 시스템</p>
</div>
""", unsafe_allow_html=True)

tab_search, tab_monitor, tab_telegram, tab_guide = st.tabs([
    "🔍 라이브 검색", "⭐ 관심 상품", "📱 텔레그램 설정", "📖 가이드",
])


# ══════════════════════════════════════════
# TAB 1: 라이브 검색
# ══════════════════════════════════════════
with tab_search:

    with st.container():
        col1, col2, col3 = st.columns([1.2, 1.2, 2.6])
        with col1:
            main_cat = st.selectbox("대분류", list(CATEGORY_MAP.keys()), key="cat_main")
        with col2:
            st.selectbox("중분류", list(CATEGORY_MAP[main_cat].keys()), key="cat_sub")
        with col3:
            st.text_input("🔎 상품 키워드", key="search_kw",
                          placeholder="예: 백팩, 무선이어폰, 텀블러...",
                          on_change=do_live_search)

        b1, b2, b3 = st.columns([1.5, 1, 3])
        with b1:
            st.button("🔍 검색", on_click=do_live_search, use_container_width=True, type="primary")
        with b2:
            st.button("🔄 초기화", on_click=reset_all, use_container_width=True)

    if st.session_state.get("search_error"):
        st.warning(f"⚠️ {st.session_state['search_error']}")

    if not st.session_state["show_results"]:
        st.markdown("""
        <div style="text-align:center;padding:3rem 0;color:#94a3b8">
            <div style="font-size:3rem">📦</div>
            <div style="font-size:1rem;margin-top:0.5rem">소싱 업체와 키워드를 설정하고 검색하세요</div>
            <div style="font-size:0.85rem;margin-top:0.3rem">
                도매매 · 도매꾹 동시 검색 | 페이지네이션으로 최대 500개 수집
            </div>
        </div>
        """, unsafe_allow_html=True)
    else:
        raw_df = pd.DataFrame(st.session_state["live_results"])
        if raw_df.empty:
            st.info("검색 결과가 없습니다. 키워드를 바꿔보세요.")
        else:
            # 소싱처별 결과 수 표시
            site_counts = raw_df["site"].value_counts().to_dict()
            site_badge  = " | ".join(f"**{s}** {n}개" for s, n in site_counts.items())
            st.markdown(f"<div style='color:#64748b;font-size:0.85rem;margin-bottom:0.5rem'>📊 {site_badge} | 총 {len(raw_df):,}개</div>", unsafe_allow_html=True)

            # 필터 바
            fc1, fc2, fc3, fc4, fc5 = st.columns([2, 1, 1, 1.2, 1.2])
            with fc1:
                kw_filter = st.text_input("결과 내 재검색", "", placeholder="상품명 필터...", label_visibility="collapsed")
            with fc2:
                site_filter = st.selectbox("소싱처", ["전체"] + list(site_counts.keys()), label_visibility="collapsed")
            with fc3:
                status_filter = st.selectbox("상태", ["전체", "정상만"], label_visibility="collapsed")
            with fc4:
                sort_col = st.selectbox("정렬",
                    ["예상 순수익(원)", "공급가(원)", "마진율(%)", "추천 판매가(원)"],
                    label_visibility="collapsed")
            with fc5:
                sort_order = st.selectbox("순서", ["높은순", "낮은순"], label_visibility="collapsed")

            df = apply_margin(raw_df, fee, margin)
            df["상태"] = df["status"].apply(lambda x: "🟢 정상" if str(x) == "Y" else "❌ 품절")

            if kw_filter:
                df = df[df["name"].str.contains(kw_filter, case=False, na=False)]
            if site_filter != "전체":
                df = df[df["site"] == site_filter]
            if status_filter == "정상만":
                df = df[df["status"] == "Y"]
            df = df.sort_values(sort_col, ascending=(sort_order == "낮은순"))

            # KPI
            ok_cnt = len(df[df["status"] == "Y"])
            avg_p  = int(df[df["status"]=="Y"]["예상 순수익(원)"].mean()) if ok_cnt > 0 else 0
            max_p  = int(df["예상 순수익(원)"].max()) if len(df) > 0 else 0

            k1, k2, k3, k4 = st.columns(4)
            k1.markdown(f'<div class="kpi-card"><div class="kpi-label">검색 결과</div><div class="kpi-value">{len(df):,}</div><div class="kpi-sub">개 상품</div></div>', unsafe_allow_html=True)
            k2.markdown(f'<div class="kpi-card"><div class="kpi-label">정상 판매</div><div class="kpi-value" style="color:#16a34a">{ok_cnt:,}</div><div class="kpi-sub">개</div></div>', unsafe_allow_html=True)
            k3.markdown(f'<div class="kpi-card"><div class="kpi-label">평균 순수익</div><div class="kpi-value">{avg_p:,}</div><div class="kpi-sub">원</div></div>', unsafe_allow_html=True)
            k4.markdown(f'<div class="kpi-card"><div class="kpi-label">최고 순수익</div><div class="kpi-value" style="color:#2563eb">{max_p:,}</div><div class="kpi-sub">원</div></div>', unsafe_allow_html=True)

            st.markdown("<br>", unsafe_allow_html=True)

            # 페이지네이션
            disp_size = 50
            total_pg  = max(1, (len(df) + disp_size - 1) // disp_size)
            page_num  = min(st.session_state["page_num"], total_pg - 1)
            page_df   = df.iloc[page_num * disp_size : (page_num + 1) * disp_size].copy()

            tracked_ids = load_tracked_db()["product_id"].astype(str).tolist()
            page_df["⭐ 관심"] = page_df["product_id"].astype(str).isin(tracked_ids)

            show_cols = ["⭐ 관심", "site", "product_id", "name", "supply_price",
                         "delivery_fee", "상태", "추천 판매가(원)", "예상 순수익(원)", "마진율(%)"]
            disp = page_df[show_cols].copy()
            disp.columns = ["⭐ 관심", "소싱처", "상품코드", "상품명", "공급가(원)",
                            "배송비(원)", "상태", "추천 판매가(원)", "예상 순수익(원)", "마진율(%)"]

            edited = st.data_editor(
                disp, use_container_width=True, hide_index=True,
                key=f"live_editor_{page_num}",
                column_config={
                    "⭐ 관심":        st.column_config.CheckboxColumn("⭐ 관심", width="small"),
                    "소싱처":         st.column_config.TextColumn("소싱처", width="small"),
                    "상품명":         st.column_config.TextColumn("상품명", width="large"),
                    "공급가(원)":     st.column_config.NumberColumn(format="%d원"),
                    "배송비(원)":     st.column_config.NumberColumn(format="%d원"),
                    "추천 판매가(원)":st.column_config.NumberColumn(format="%d원"),
                    "예상 순수익(원)":st.column_config.NumberColumn(format="%d원"),
                    "마진율(%)":      st.column_config.NumberColumn(format="%.1f%%"),
                },
            )

            for i in range(len(edited)):
                if edited.iloc[i]["⭐ 관심"] != disp.iloc[i]["⭐ 관심"]:
                    upsert_tracked_product(page_df.iloc[i].to_dict(), 1 if edited.iloc[i]["⭐ 관심"] else 0)
                    st.rerun()

            pn1, pn2, pn3 = st.columns([1, 3, 1])
            with pn1:
                if st.button("◀ 이전", disabled=(page_num == 0), use_container_width=True):
                    st.session_state["page_num"] = page_num - 1
                    st.rerun()
            with pn2:
                st.markdown(f"<div style='text-align:center;color:#64748b;font-size:0.85rem;padding-top:0.5rem'>{page_num+1} / {total_pg} 페이지 | 총 {len(df):,}개</div>", unsafe_allow_html=True)
            with pn3:
                if st.button("다음 ▶", disabled=(page_num >= total_pg - 1), use_container_width=True):
                    st.session_state["page_num"] = page_num + 1
                    st.rerun()


# ══════════════════════════════════════════
# TAB 2: 관심 상품
# ══════════════════════════════════════════
with tab_monitor:
    tracked_df = load_tracked_db()

    if tracked_df.empty:
        st.markdown("""
        <div style="text-align:center;padding:3rem 0;color:#94a3b8">
            <div style="font-size:3rem">⭐</div>
            <div style="font-size:1rem;margin-top:0.5rem">관심 상품이 없습니다</div>
        </div>
        """, unsafe_allow_html=True)
    else:
        total_m = len(tracked_df)
        oos_m   = len(tracked_df[tracked_df["status"] != "Y"])
        tracked_df = apply_margin(tracked_df, fee, margin)
        avg_m = int(tracked_df[tracked_df["status"]=="Y"]["예상 순수익(원)"].mean()) if total_m - oos_m > 0 else 0

        k1, k2, k3, k4 = st.columns(4)
        k1.markdown(f'<div class="kpi-card"><div class="kpi-label">관심 상품</div><div class="kpi-value">{total_m}</div></div>', unsafe_allow_html=True)
        k2.markdown(f'<div class="kpi-card"><div class="kpi-label">정상</div><div class="kpi-value" style="color:#16a34a">{total_m-oos_m}</div></div>', unsafe_allow_html=True)
        k3.markdown(f'<div class="kpi-card"><div class="kpi-label">품절</div><div class="kpi-value" style="color:#dc2626">{oos_m}</div></div>', unsafe_allow_html=True)
        k4.markdown(f'<div class="kpi-card"><div class="kpi-label">평균 순수익</div><div class="kpi-value">{avg_m:,}</div></div>', unsafe_allow_html=True)

        st.markdown("<br>", unsafe_allow_html=True)

        mf1, mf2 = st.columns([2, 1])
        with mf1:
            m_filter = st.text_input("상품명 검색", "", placeholder="관심 상품 내 검색...", label_visibility="collapsed")
        with mf2:
            m_status = st.selectbox("상태", ["전체", "정상만", "품절만"], label_visibility="collapsed")

        mdf = tracked_df.copy()
        mdf["상태"] = mdf["status"].apply(lambda x: "🟢 정상" if str(x) == "Y" else "❌ 품절")
        if m_filter:
            mdf = mdf[mdf["name"].str.contains(m_filter, case=False, na=False)]
        if m_status == "정상만":
            mdf = mdf[mdf["status"] == "Y"]
        elif m_status == "품절만":
            mdf = mdf[mdf["status"] != "Y"]

        mdf["❌ 해제"] = True
        m_cols = [c for c in ["❌ 해제","site","product_id","name","supply_price","delivery_fee",
                               "상태","추천 판매가(원)","예상 순수익(원)","마진율(%)","updated_at"] if c in mdf.columns]
        mdf_disp = mdf[m_cols].copy()

        edited_m = st.data_editor(
            mdf_disp,
            column_config={
                "❌ 해제":         st.column_config.CheckboxColumn("❌ 해제", default=True, width="small"),
                "supply_price":    st.column_config.NumberColumn("공급가(원)", format="%d원"),
                "delivery_fee":    st.column_config.NumberColumn("배송비(원)", format="%d원"),
                "추천 판매가(원)": st.column_config.NumberColumn(format="%d원"),
                "예상 순수익(원)": st.column_config.NumberColumn(format="%d원"),
                "마진율(%)":       st.column_config.NumberColumn(format="%.1f%%"),
            },
            disabled=[c for c in m_cols if c != "❌ 해제"],
            use_container_width=True, hide_index=True, key="tracked_editor",
        )

        changed = False
        for i in range(len(edited_m)):
            if not edited_m.iloc[i]["❌ 해제"]:
                upsert_tracked_product(mdf.iloc[i].to_dict(), 0)
                changed = True
        if changed:
            st.rerun()

        st.markdown("<br>", unsafe_allow_html=True)
        if st.button("📱 관심 상품 현황을 텔레그램으로 전송", use_container_width=True):
            lines = [f"📊 관심 상품 현황\n전체 {total_m}개 | 정상 {total_m-oos_m}개 | 품절 {oos_m}개\n"]
            for _, row in tracked_df.iterrows():
                icon = "🟢" if row["status"] == "Y" else "❌"
                lines.append(f"{icon} {row['name'][:25]} — {int(row['추천 판매가(원)']):,}원 / 수익 {int(row['예상 순수익(원)']):,}원")
            if send_telegram_message("\n".join(lines)):
                st.success("전송 완료!")
            else:
                st.error("전송 실패")


# ══════════════════════════════════════════
# TAB 3: 텔레그램 설정
# ══════════════════════════════════════════
with tab_telegram:
    st.markdown("### 📱 텔레그램 알림 설정")
    col_a, col_b = st.columns(2)
    with col_a:
        st.markdown("""
        #### 1단계 — 봇 만들기
        1. 텔레그램 앱 → **@BotFather** 검색
        2. `/newbot` 입력 → 이름 설정
        3. 발급된 **토큰** 복사

        #### 2단계 — 채팅방 ID 확인
        1. 만든 봇에게 메시지 전송
        2. 브라우저에서 접속:
        ```
        https://api.telegram.org/bot[토큰]/getUpdates
        ```
        3. `"chat":{"id":` 뒤 숫자 = 채팅방 ID
        """)
    with col_b:
        st.markdown("#### 3단계 — Secrets 등록")
        st.code("""DOMEGGOOK_API_KEY  = "..."
TELEGRAM_BOT_TOKEN = "..."
TELEGRAM_CHAT_ID   = "..."
""", language="toml")
        st.markdown("#### 4단계 — 테스트")
        test_msg = st.text_input("테스트 메시지", value="소싱레이더 연동 테스트 ✅")
        if st.button("📤 테스트 발송", type="primary", use_container_width=True):
            ok = send_telegram_message(test_msg)
            st.success("✅ 발송 성공!") if ok else st.error("❌ 실패. 토큰/채팅방 ID 확인")

    st.markdown("---")
    st.markdown("""
    | 상황 | 알림 내용 |
    |------|----------|
    | 매일 새벽 4시 | 관심 상품 전체 점검 리포트 |
    | 품절 전환 | ❌ 즉시 품절 알림 |
    | 공급가 인상 | 🔴 인상 전/후 비교 |
    | 배치 완료 | ✅ 점검 완료 요약 |
    """)


# ══════════════════════════════════════════
# TAB 4: 가이드
# ══════════════════════════════════════════
with tab_guide:
    st.markdown("### 📖 소싱레이더 사용 가이드")

    with st.expander("🏪 소싱 업체 설명", expanded=True):
        st.markdown("""
        | 업체 | 방식 | 특징 |
        |------|------|------|
        | **도매매** | 공식 API | 도매꾹 계열 B2B 배송대행 플랫폼 |
        | **도매꾹** | 공식 API | 국내 최대 도매 마켓, 다양한 카테고리 |
        | **온채널** | 웹 파싱 | 위탁판매 전문, 공식 API 미제공 |
        """)

    with st.expander("📊 검색 수량 선택 기준"):
        st.markdown("""
        | 옵션 | 총 상품 수 | 소요 시간 | 추천 상황 |
        |------|-----------|-----------|----------|
        | 빠른 탐색 | 50개 | 1~2초 | 빠른 시장 파악 |
        | 일반 검색 | 100개 | 2~4초 | 일반 소싱 분석 |
        | 심층 분석 | 200개 | 4~8초 | 경쟁 상품 전체 파악 |
        | 대량 수집 | 500개 | 10~20초 | 카테고리 전체 분석 |
        """)

    with st.expander("💡 마진 계산 공식"):
        st.markdown("""
        ```
        추천 판매가 = (공급가 + 배송비) ÷ (1 - 수수료율 - 목표마진율)
        예상 순수익 = 판매가 - (판매가 × 수수료율) - 공급가 - 배송비
        ```
        **예시** (네이버 8% | 밸런스형 20%, 공급가 10,000원 + 배송비 3,000원)
        - 추천 판매가 = 13,000 ÷ 0.72 = **18,060원**
        - 예상 순수익 = 18,060 - 1,445 - 10,000 - 3,000 = **3,615원**
        """)
