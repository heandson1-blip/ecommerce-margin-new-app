import streamlit as st
import sqlite3
import pandas as pd
from utils import calculate_target_price, calculate_expected_profit
from database import init_db, upsert_tracked_product
from domeme_client import DomeameClient

# ✅ API KEY: Streamlit Secrets에서 안전하게 불러오기
# 로컬 테스트 시 .streamlit/secrets.toml 파일에 키를 입력하세요
try:
    API_KEY = st.secrets["DOMEGGOOK_API_KEY"]
except Exception:
    API_KEY = ""
    st.warning("⚠️ API 키가 설정되지 않았습니다. .streamlit/secrets.toml 파일을 확인하세요.", icon="⚠️")

client = DomeameClient(api_key=API_KEY)

# ✅ DB 초기화: 앱 시작 시 한 번만 실행
init_db()

st.set_page_config(layout="wide", page_title="이커머스 마진 분석 시스템", page_icon="🛒")
st.markdown("<style>.block-container {padding-top: 1rem;}</style>", unsafe_allow_html=True)

# 카테고리 맵
CATEGORY_MAP = {
    "전체보기": {"전체보기": "0000"},
    "패션의류": {"전체보기": "01", "여성의류": "0101", "남성의류": "0102", "언더웨어": "0103"},
    "패션잡화": {"전체보기": "02", "신발": "0201", "가방": "0202", "화장품/미용": "0204"},
    "디지털/가전": {"전체보기": "04", "음향가전": "0401", "생활가전": "0402", "계절가전": "0403"},
    "생활/건강": {"전체보기": "06", "생활용품": "0601", "건강/의료용품": "0602"},
    "식품": {"전체보기": "09", "가공식품": "0901", "건강식품": "0902", "농축수산물": "0903"},
    "가구/인테리어": {"전체보기": "10", "가구": "1001", "인테리어소품": "1002"},
}

# 세션 초기화
if "live_results" not in st.session_state:
    st.session_state["live_results"] = []
if "show_results" not in st.session_state:
    st.session_state["show_results"] = False
if "search_error" not in st.session_state:
    st.session_state["search_error"] = None


def load_tracked_data_from_db():
    """DB에서 관심 상품 목록을 불러옵니다."""
    try:
        conn = sqlite3.connect("sourcing.db")
        df = pd.read_sql_query("SELECT * FROM products WHERE is_tracked = 1", conn)
        conn.close()
        return df if not df.empty else pd.DataFrame(
            columns=["product_id", "site", "name", "supply_price", "delivery_fee", "status", "is_tracked"]
        )
    except Exception as e:
        st.error(f"DB 로드 오류: {e}")
        return pd.DataFrame(
            columns=["product_id", "site", "name", "supply_price", "delivery_fee", "status"]
        )


def do_live_search():
    """라이브 검색 실행 및 결과 세션 저장"""
    st.session_state["search_error"] = None
    kw = st.session_state.get("search_kw", "")
    cat_code = CATEGORY_MAP[st.session_state["cat_main"]][st.session_state["cat_sub"]]
    site = st.session_state.get("sourcing_site", "전체보기")

    if not API_KEY:
        st.session_state["search_error"] = "API 키가 없어 검색할 수 없습니다. secrets 설정을 확인하세요."
        return

    results = []
    try:
        if site in ["전체보기", "도매매"]:
            results.extend(client.fetch_product_list(market="supply", keyword=kw, category_code=cat_code))
        if site in ["전체보기", "도매꾹"]:
            results.extend(client.fetch_product_list(market="dome", keyword=kw, category_code=cat_code))
    except Exception as e:
        st.session_state["search_error"] = f"API 통신 오류: {e}"
        return

    if not results:
        st.session_state["search_error"] = "검색 결과가 없습니다. 키워드나 카테고리를 변경해보세요."
        st.session_state["live_results"] = []
        st.session_state["show_results"] = True
        return

    df = pd.DataFrame(results).drop_duplicates(subset=["product_id"])
    st.session_state["live_results"] = df.to_dict("records")
    st.session_state["show_results"] = True


def reset_all():
    st.session_state["search_kw"] = ""
    st.session_state["live_results"] = []
    st.session_state["show_results"] = False
    st.session_state["search_error"] = None
    st.rerun()


# ==========================================
# 사이드바 (소싱 환경 설정)
# ==========================================
with st.sidebar:
    st.header("⚙️ 소싱 환경 설정")
    sourcing_site = st.selectbox("업체 선택", ["전체보기", "도매매", "도매꾹"], key="sourcing_site")
    platform = st.selectbox("판매 플랫폼", ["네이버 스마트스토어 (8%)", "쿠팡 (11%)", "지마켓/옥션 (14%)"])
    margin_strategy = st.select_slider(
        "마진 전략",
        options=["안정형 (10%)", "밸런스형 (20%)", "고마진형 (40%)"]
    )

    fee = {"네이버": 0.08, "쿠팡": 0.11, "지마켓": 0.14}[
        next(k for k in ["네이버", "쿠팡", "지마켓"] if k in platform)
    ]
    margin = {"안정형": 0.10, "밸런스형": 0.20, "고마진형": 0.40}[margin_strategy.split(" ")[0]]

    st.success(f"수수료: {int(fee * 100)}% | 목표마진: {int(margin * 100)}%")

    st.divider()

    # 관심 상품 요약 배지
    tracked_summary = load_tracked_data_from_db()
    total = len(tracked_summary)
    oos = len(tracked_summary[tracked_summary["status"] != "Y"]) if not tracked_summary.empty else 0
    st.markdown("**📊 관심 상품 현황**")
    col_a, col_b = st.columns(2)
    col_a.metric("전체", total)
    col_b.metric("❌ 품절", oos, delta=None)

    st.divider()
    st.caption("매일 새벽 4시에 관심 상품 상태가 자동 업데이트됩니다.")


# ==========================================
# 메인 화면 - 검색창
# ==========================================
st.title("🛒 이커머스 마진 분석 시스템")

col1, col2, col3, col4 = st.columns([1.5, 1.5, 2, 1])
with col1:
    main_cat = st.selectbox("대분류", list(CATEGORY_MAP.keys()), key="cat_main")
with col2:
    st.selectbox("중분류(선택)", list(CATEGORY_MAP[main_cat].keys()), key="cat_sub")
with col3:
    st.text_input("상품 키워드 검색", key="search_kw", placeholder="예: 백팩, 무선이어폰...", on_change=do_live_search)
with col4:
    st.write("###")
    st.button("🔍 라이브 검색", on_click=do_live_search, use_container_width=True)
    st.button("🔄 초기화", on_click=reset_all, use_container_width=True)

st.divider()

# ==========================================
# 메인 화면 중단 - 라이브 검색 결과
# ==========================================
st.subheader("📦 라이브 검색 결과 및 마진 분석")

# 검색 오류 표시
if st.session_state.get("search_error"):
    st.error(st.session_state["search_error"])

if st.session_state["show_results"]:
    df = pd.DataFrame(st.session_state["live_results"])

    if df.empty:
        st.warning("검색 결과가 없습니다. 다른 키워드나 카테고리를 시도해보세요.")
    else:
        # 결과 내 재검색
        kw_filter = st.text_input("🔎 결과 내 재검색", "", placeholder="상품명으로 필터링...")
        if kw_filter:
            df = df[df["name"].str.contains(kw_filter, case=False, na=False)].copy()

        if df.empty:
            st.warning("필터 조건에 맞는 상품이 없습니다.")
        else:
            # 마진 계산
            df["추천 판매가"] = df.apply(
                lambda x: calculate_target_price(x["supply_price"], x["delivery_fee"], fee, margin), axis=1
            )
            df["예상 순수익"] = df.apply(
                lambda x: calculate_expected_profit(x["추천 판매가"], x["supply_price"], x["delivery_fee"], fee), axis=1
            )
            df["상태"] = df["status"].apply(lambda x: "🟢 정상" if str(x) == "Y" else "❌ 품절")

            # 관심 등록 여부 체크
            tracked_data = load_tracked_data_from_db()
            tracked_ids = tracked_data["product_id"].tolist() if not tracked_data.empty else []
            df["⭐ 관심 등록"] = df["product_id"].apply(lambda x: str(x) in [str(t) for t in tracked_ids])

            cols = ["⭐ 관심 등록", "site", "product_id", "name", "supply_price", "delivery_fee", "상태", "추천 판매가", "예상 순수익"]
            display_df = df[cols].copy()
            display_df.columns = ["⭐ 관심 등록", "소싱처", "상품코드", "상품명", "공급가(원)", "배송비(원)", "상태", "추천 판매가(원)", "예상 순수익(원)"]

            st.info(f"총 **{len(display_df)}개** 상품 조회됨")

            edited_df = st.data_editor(
                display_df,
                use_container_width=True,
                hide_index=True,
                key="live_editor",
                column_config={
                    "⭐ 관심 등록": st.column_config.CheckboxColumn("⭐ 관심"),
                    "추천 판매가(원)": st.column_config.NumberColumn(format="%d원"),
                    "예상 순수익(원)": st.column_config.NumberColumn(format="%d원"),
                    "공급가(원)": st.column_config.NumberColumn(format="%d원"),
                    "배송비(원)": st.column_config.NumberColumn(format="%d원"),
                },
            )

            # 체크박스 변경 감지 → DB 반영
            changed = False
            for i in range(len(edited_df)):
                before = display_df.iloc[i]["⭐ 관심 등록"]
                after = edited_df.iloc[i]["⭐ 관심 등록"]
                if after != before:
                    target_product = df.iloc[i].to_dict()
                    upsert_tracked_product(target_product, 1 if after else 0)
                    changed = True
            if changed:
                st.rerun()

st.divider()

# ==========================================
# 메인 화면 하단 - 관심 상품 모니터링
# ==========================================
st.subheader("⭐ 나의 관심 상품 모니터링")
tracked_df = load_tracked_data_from_db()

if not tracked_df.empty:
    # 요약 배지
    total_t = len(tracked_df)
    oos_t = len(tracked_df[tracked_df["status"] != "Y"])
    b1, b2, b3 = st.columns(3)
    b1.metric("📦 전체 상품", total_t)
    b2.metric("❌ 품절", oos_t)
    b3.metric("🟢 정상", total_t - oos_t)

    # 마진 계산
    tracked_df["추천 판매가"] = tracked_df.apply(
        lambda x: calculate_target_price(x["supply_price"], x["delivery_fee"], fee, margin), axis=1
    )
    tracked_df["예상 순수익"] = tracked_df.apply(
        lambda x: calculate_expected_profit(x["추천 판매가"], x["supply_price"], x["delivery_fee"], fee), axis=1
    )
    tracked_df["상태"] = tracked_df["status"].apply(lambda x: "🟢 정상" if str(x) == "Y" else "❌ 품절")
    tracked_df["❌ 추적 해제"] = True

    m_cols = ["❌ 추적 해제", "site", "product_id", "name", "supply_price", "delivery_fee", "상태", "추천 판매가", "예상 순수익"]
    display_tracked_df = tracked_df[m_cols].copy()
    display_tracked_df.columns = ["❌ 추적 해제", "소싱처", "상품코드", "상품명", "공급가(원)", "배송비(원)", "상태", "추천 판매가(원)", "예상 순수익(원)"]

    edited_tracked_df = st.data_editor(
        display_tracked_df,
        column_config={
            "❌ 추적 해제": st.column_config.CheckboxColumn("❌ 추적 해제", default=True),
            "추천 판매가(원)": st.column_config.NumberColumn(format="%d원"),
            "예상 순수익(원)": st.column_config.NumberColumn(format="%d원"),
            "공급가(원)": st.column_config.NumberColumn(format="%d원"),
            "배송비(원)": st.column_config.NumberColumn(format="%d원"),
        },
        disabled=["소싱처", "상품코드", "상품명", "공급가(원)", "배송비(원)", "상태", "추천 판매가(원)", "예상 순수익(원)"],
        use_container_width=True,
        hide_index=True,
        key="tracked_editor",
    )

    # 체크 해제 시 DB에서 추적 종료
    track_changes = False
    for i in range(len(edited_tracked_df)):
        if not edited_tracked_df.iloc[i]["❌ 추적 해제"]:
            target_p = tracked_df.iloc[i].to_dict()
            upsert_tracked_product(target_p, 0)
            track_changes = True

    if track_changes:
        st.rerun()
else:
    st.info("검색 결과에서 '⭐ 관심 등록'을 체크하면 여기에 모니터링 리스트가 표시됩니다.")
