import streamlit as st
import sqlite3
import pandas as pd
import requests as req
from datetime import datetime
from utils import calculate_target_price, calculate_expected_profit
from database import init_db, upsert_tracked_product
from domeme_client import DomeameClient
from notifications import send_telegram_message

try:
    from onchannel_client import OnchannelClient
    OC_AVAILABLE = True
except ImportError:
    OC_AVAILABLE = False

st.set_page_config(layout="wide", page_title="소싱레이더 | 이커머스 마진 분석",
                   page_icon="📡", initial_sidebar_state="expanded")

st.markdown("""
<style>
.block-container{padding-top:1.2rem;padding-bottom:2rem;max-width:1500px}
.stApp{background-color:#F7F8FA}
.main-header{background:linear-gradient(135deg,#1a1a2e 0%,#16213e 50%,#0f3460 100%);
    border-radius:16px;padding:1.5rem 2rem;margin-bottom:1.5rem}
.main-header h1{font-size:1.8rem;font-weight:700;margin:0;color:white}
.main-header p{font-size:.9rem;margin:.3rem 0 0;color:#94a3b8}
.kpi-card{background:white;border-radius:12px;padding:1.2rem 1.4rem;
    border:1px solid #e2e8f0;box-shadow:0 1px 3px rgba(0,0,0,.06)}
.kpi-label{font-size:.72rem;color:#64748b;font-weight:600;text-transform:uppercase;
    letter-spacing:.05em;margin-bottom:.3rem}
.kpi-value{font-size:1.7rem;font-weight:700;color:#1e293b;line-height:1}
.kpi-sub{font-size:.72rem;color:#94a3b8;margin-top:.2rem}
section[data-testid="stSidebar"]{background:#1a1a2e !important}
section[data-testid="stSidebar"] *{color:#cbd5e1 !important}
.stButton>button{border-radius:8px !important;font-weight:600 !important;transition:all .2s !important}
.stTabs [data-baseweb="tab-list"]{gap:4px;background:#f1f5f9;border-radius:10px;padding:4px}
.stTabs [data-baseweb="tab"]{border-radius:8px !important;font-weight:500 !important}
.stTabs [aria-selected="true"]{background:white !important;box-shadow:0 1px 3px rgba(0,0,0,.1) !important}
footer{visibility:hidden}
</style>
""", unsafe_allow_html=True)

# ── Secrets ──────────────────────────────────────────────────
try:
    DOME_KEY   = st.secrets["DOMEGGOOK_API_KEY"]
    GEMINI_KEY = st.secrets.get("GEMINI_API_KEY","")
    OC_ID      = st.secrets.get("ONCHANNEL_ID","")
    OC_PW      = st.secrets.get("ONCHANNEL_PW","")
except Exception:
    DOME_KEY=GEMINI_KEY=OC_ID=OC_PW=""

init_db()
client    = DomeameClient(api_key=DOME_KEY) if DOME_KEY else None
oc_client = OnchannelClient(user_id=OC_ID, password=OC_PW) if OC_AVAILABLE else None

CATEGORY_MAP={
    "전체보기":{"전체보기":"0000"},
    "패션의류":{"전체보기":"01","여성의류":"0101","남성의류":"0102","언더웨어":"0103"},
    "패션잡화":{"전체보기":"02","신발":"0201","가방":"0202","화장품/미용":"0204"},
    "디지털/가전":{"전체보기":"04","음향가전":"0401","생활가전":"0402","계절가전":"0403"},
    "생활/건강":{"전체보기":"06","생활용품":"0601","건강/의료용품":"0602"},
    "식품":{"전체보기":"09","가공식품":"0901","건강식품":"0902","농축수산물":"0903"},
    "가구/인테리어":{"전체보기":"10","가구":"1001","인테리어소품":"1002"},
}
PLATFORM_FEE={"네이버 스마트스토어":0.08,"쿠팡":0.11,"지마켓/옥션":0.14}
MARGIN_MAP={"안정형  (10%)":0.10,"밸런스형 (20%)":0.20,"고마진형 (40%)":0.40}
FETCH_PRESETS={"빠른 탐색  (50개)":(50,1),"일반 검색  (100개)":(50,2),
               "심층 분석  (200개)":(50,4),"대량 수집  (500개)":(50,10)}

for k,v in {"live_results":[],"show_results":False,"search_error":None,
            "page_num":0,"ai_result":None,"live_view":"table","mon_view":"table"}.items():
    if k not in st.session_state:
        st.session_state[k]=v

# ── 헬퍼 ─────────────────────────────────────────────────────
def fmt_dt(dt_str):
    """26.06.14 형식"""
    if not dt_str or str(dt_str) in ("nan","None",""):
        return ""
    try:
        dt = datetime.strptime(str(dt_str)[:19], "%Y-%m-%d %H:%M:%S")
        return dt.strftime("%y.%m.%d")
    except Exception:
        return str(dt_str)[:10]

def load_tracked_db():
    try:
        conn=sqlite3.connect("sourcing.db")
        df=pd.read_sql_query("SELECT * FROM products WHERE is_tracked=1 ORDER BY updated_at DESC",conn)
        conn.close()
        for col,default in [("seller_grade",""),("image_url","")]:
            if col not in df.columns: df[col]=default
        return df
    except Exception as e:
        st.error(f"DB 오류: {e}"); return pd.DataFrame()

def apply_margin(df, fee, margin):
    df=df.copy()
    df["추천 판매가(원)"]=df.apply(lambda r:calculate_target_price(r["supply_price"],r["delivery_fee"],fee,margin),axis=1)
    df["예상 순수익(원)"]=df.apply(lambda r:calculate_expected_profit(r["추천 판매가(원)"],r["supply_price"],r["delivery_fee"],fee),axis=1)
    df["마진율(%)"]=df.apply(lambda r:round(r["예상 순수익(원)"]/r["추천 판매가(원)"]*100,1) if r["추천 판매가(원)"]>0 else 0,axis=1)
    return df

def do_live_search():
    st.session_state.update({"search_error":None,"page_num":0,
                              "live_results":[],"ai_result":None,"show_results":False})
    kw=st.session_state.get("search_kw","").strip()
    cat=CATEGORY_MAP[st.session_state["cat_main"]][st.session_state["cat_sub"]]
    sites=st.session_state.get("sourcing_sites",["도매매","도매꾹"])
    pg_size,max_pg=FETCH_PRESETS.get(st.session_state.get("fetch_preset","일반 검색  (100개)"),(50,2))
    results=[]; errors=[]

    if any(s in sites for s in ["도매매","도매꾹"]):
        if not DOME_KEY: errors.append("도매매/도매꾹 API 키 없음")
        elif client:
            try:
                if "도매매" in sites:
                    results.extend(client.fetch_product_list(market="supply",keyword=kw,category_code=cat,page_size=pg_size,max_pages=max_pg))
                if "도매꾹" in sites:
                    results.extend(client.fetch_product_list(market="dome",keyword=kw,category_code=cat,page_size=pg_size,max_pages=max_pg))
            except Exception as e: errors.append(f"도매매/도매꾹: {e}")

    if "온채널" in sites and oc_client:
        if not OC_ID or not OC_PW:
            errors.append("온채널 ID/PW 미설정 (Secrets 확인)")
        elif kw:
            try:
                oc=oc_client.fetch_product_list(keyword=kw,page_size=pg_size*max_pg,max_pages=max_pg)
                results.extend(oc)
            except Exception as e: errors.append(f"온채널: {e}")

    if errors: st.session_state["search_error"]=" | ".join(errors)
    if not results and not errors: st.session_state["search_error"]="검색 결과 없음"
    elif results:
        df=pd.DataFrame(results).drop_duplicates(subset=["product_id"])
        for col,default in [("seller_grade",""),("image_url","")]:
            if col not in df.columns: df[col]=default
        st.session_state["live_results"]=df.to_dict("records")
    st.session_state["show_results"]=True

def reset_all():
    st.session_state.update({"search_kw":"","live_results":[],"show_results":False,
                              "search_error":None,"page_num":0,"ai_result":None})
    st.rerun()

def do_track(prod, is_track):
    """관심 등록/해제. 등록 시 상세 API로 등급/배송비/이미지 즉시 갱신."""
    if is_track and client and prod.get("site") in ["도매매","도매꾹"]:
        detail=client.fetch_item_detail(str(prod["product_id"]))
        if detail:
            for k,v in detail.items():
                if v: prod[k]=v
    upsert_tracked_product(prod, is_track)

def render_cards(df, tracked_ids, id_prefix, on_toggle):
    """공통 카드 그리드 (3열)"""
    per_row=3
    for i in range(0, len(df), per_row):
        cols=st.columns(per_row)
        for ci, (_, row) in enumerate(df.iloc[i:i+per_row].iterrows()):
            with cols[ci]:
                grade=str(row.get("seller_grade","")).strip()
                img=str(row.get("image_url","")).strip()
                profit=int(row.get("예상 순수익(원)",0))
                sale=int(row.get("추천 판매가(원)",0))
                mp=float(row.get("마진율(%)",0))
                is_t=str(row["product_id"]) in tracked_ids

                if img and img.startswith("http"):
                    try: st.image(img, width=220)
                    except: st.markdown("📦")
                else:
                    st.markdown("<div style='height:90px;background:#f1f5f9;border-radius:8px;"
                                "display:flex;align-items:center;justify-content:center;"
                                "font-size:2.5rem;margin-bottom:6px'>📦</div>",
                                unsafe_allow_html=True)

                gc={"S":"#f59e0b","A":"#3b82f6","B":"#22c55e","C":"#eab308",
                    "D":"#f97316","E":"#ef4444"}.get(
                    grade[0].upper() if grade and grade[0].isalpha() else "","#94a3b8")

                st.markdown(f"""
<div style="font-size:.82rem;font-weight:500;color:#1e293b;white-space:nowrap;
    overflow:hidden;text-overflow:ellipsis;margin-bottom:3px" title="{row['name']}">
    {row['name'][:32]}
</div>
<div style="font-size:.7rem;color:#94a3b8;margin-bottom:3px">
    {row.get('site','')} | {row.get('product_id','')}
</div>
<div style="font-size:.75rem;color:#475569;margin-bottom:2px">
    공급가 <b>{int(row['supply_price']):,}원</b> 배송비 <b>{int(row['delivery_fee']):,}원</b>
</div>
<div style="font-size:.9rem;font-weight:700;color:#2563eb;margin-bottom:2px">
    판매가 {sale:,}원 &nbsp; 순수익 {profit:,}원
</div>
<div style="font-size:.72rem;color:#64748b">
    마진 <b>{mp:.1f}%</b> &nbsp;|&nbsp;
    등급 <span style="color:{gc};font-weight:600">{grade if grade else '확인중'}</span> &nbsp;|&nbsp;
    {row.get('상태','')}
</div>""", unsafe_allow_html=True)

                label="⭐ 등록됨" if is_t else "☆ 관심 등록"
                if st.button(label, key=f"{id_prefix}_{row['product_id']}",
                             use_container_width=True):
                    on_toggle(row.to_dict(), 0 if is_t else 1)
                    st.rerun()

def send_tg_long(text: str, prefix: str = "📡 소싱레이더") -> bool:
    """텔레그램 긴 메시지 분할 전송 (3800자씩)"""
    import time as _time
    chunk_size = 3800
    chunks = [text[i:i+chunk_size] for i in range(0, len(text), chunk_size)]
    total = len(chunks)
    success = True
    for i, chunk in enumerate(chunks):
        header = prefix if total == 1 else f"{prefix} ({i+1}/{total})"
        ok = send_telegram_message(f"{header}\n\n{chunk}")
        if not ok:
            success = False
        if i < len(chunks) - 1:
            _time.sleep(0.5)
    return success

def compact_ai(items_df, fee, margin, platform_name, margin_name):
    """Gemini 핵심 축약 소싱 분석"""
    if not GEMINI_KEY:
        return "GEMINI_API_KEY 미설정"

    rows = []
    for _, r in items_df.iterrows():
        profit = int(r.get("예상 순수익(원)", 0))
        sale   = int(r.get("추천 판매가(원)", 0))
        supply = int(r.get("supply_price", 0))
        deliv  = int(r.get("delivery_fee", 0))
        mp     = float(r.get("마진율(%)", 0))
        grade  = r.get("seller_grade","미확인") or "미확인"
        rows.append(
            f"{r['name'][:28]} ({r.get('site','')})\n"
            f"  원가{supply+deliv:,}원 판매가{sale:,}원 순수익{profit:,}원/건 "
            f"마진{mp:.1f}% 등급{grade}"
        )

    prompt = f"""이커머스 소싱 전문가로서 마케팅과 판매 관점에서 핵심만 분석하세요.

판매 설정: {platform_name} 수수료{int(fee*100)}% / 목표마진 {int(margin*100)}%

분석 상품:
{chr(10).join(rows)}

아래 형식으로만 출력하세요. 특수기호(-,#,*,•) 없이 한글과 숫자만 사용하세요.

즉시 소싱 추천 TOP3
1 상품명 이유한줄
2 상품명 이유한줄
3 상품명 이유한줄

제외 권장
상품명 이유한줄

개별 판정
상품명 판정(강력추천/추천/주의/비추천) 마진경쟁력(상중하) 리스크한줄 월50건수익 원

이번달 전략
핵심 액션 3가지를 번호로

공통 주의사항
내용 2줄 이내

각 섹션 5줄 이내, 수치 포함, 간결하게."""

    try:
        resp = req.post(
            f"https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash-lite:generateContent?key={GEMINI_KEY}",
            headers={"Content-Type":"application/json"},
            json={"contents":[{"parts":[{"text":prompt}]}],
                  "generationConfig":{"maxOutputTokens":1800,"temperature":0.1}},
            timeout=60,
        )
        if resp.status_code == 200:
            return resp.json()["candidates"][0]["content"]["parts"][0]["text"]
        return f"Gemini 오류 {resp.status_code}: {resp.text[:200]}"
    except Exception as e:
        return f"AI 연결 오류: {e}"

# ── 사이드바 ─────────────────────────────────────────────────
with st.sidebar:
    st.markdown("## 📡 소싱레이더")
    st.markdown("---")
    st.markdown("#### 소싱 설정")
    site_opts = ["도매매","도매꾹"]
    if OC_AVAILABLE: site_opts.append("온채널")
    sourcing_sites = st.multiselect("소싱 업체", options=site_opts,
                                    default=["도매매","도매꾹"], key="sourcing_sites")
    if OC_AVAILABLE:
        oc_status = "연동됨" if (OC_ID and OC_PW) else "ID/PW 미설정"
        st.caption(f"온채널: {oc_status} (로그인 필요)")
    fetch_preset = st.selectbox("검색 수량", list(FETCH_PRESETS.keys()), index=1, key="fetch_preset")

    st.markdown("#### 판매 전략")
    platform_name = st.selectbox("판매 플랫폼", list(PLATFORM_FEE.keys()))
    margin_name   = st.select_slider("마진 전략", options=list(MARGIN_MAP.keys()))
    fee    = PLATFORM_FEE[platform_name]
    margin = MARGIN_MAP[margin_name]

    st.markdown(f"""<div style="background:#0f3460;border-radius:10px;padding:.8rem 1rem;margin-top:.5rem">
        <div style="color:#94a3b8;font-size:.72rem;font-weight:600">현재 설정</div>
        <div style="color:white;font-size:1rem;font-weight:700;margin-top:.2rem">
            수수료 {int(fee*100)}% / 목표마진 {int(margin*100)}%</div>
        <div style="color:#64748b;font-size:.72rem;margin-top:.2rem">배수 ÷{round(1-fee-margin,2)}</div>
    </div>""", unsafe_allow_html=True)

    st.markdown("---")
    # 사이드바 관심 상품 요약
    t_df = load_tracked_db()
    total_t = len(t_df)
    if not t_df.empty:
        t_calc = apply_margin(t_df, fee, margin)
        avg_profit_t = int(t_calc["예상 순수익(원)"].mean())
        best_margin  = round(t_calc["마진율(%)"].max(), 1)
    else:
        avg_profit_t = 0; best_margin = 0

    st.markdown("#### 관심 상품 현황")
    c1, c2 = st.columns(2)
    c1.metric("등록 상품", total_t)
    c2.metric("평균 순수익", f"{avg_profit_t:,}원")

    st.markdown("---")
    st.markdown("#### 텔레그램")
    try: tg_ok = st.secrets.get("TELEGRAM_BOT_TOKEN","") not in ["","봇토큰_입력"]
    except: tg_ok = False
    st.markdown(f"상태: {'연동됨' if tg_ok else '미설정'}")
    if st.button("테스트 발송", use_container_width=True):
        ok = send_telegram_message(f"소싱레이더 연동 테스트\n관심상품 {total_t}개 / 평균순수익 {avg_profit_t:,}원")
        st.success("발송 완료") if ok else st.error("발송 실패")

    st.markdown("---")
    ai_ok = bool(GEMINI_KEY)
    st.markdown(f"#### AI 분석 (Gemini 무료)\n{'사용 가능' if ai_ok else 'GEMINI_API_KEY 미설정'}")
    st.markdown("---")
    st.caption("소싱레이더 v5.2")

# ── 메인 헤더 ────────────────────────────────────────────────
st.markdown("""<div class="main-header">
    <h1>📡 소싱레이더</h1>
    <p>도매매 도매꾹 온채널 실시간 통합 마진 분석 시스템</p>
</div>""", unsafe_allow_html=True)

tab1, tab2, tab3, tab4 = st.tabs(["🔍 라이브 검색","⭐ 관심 상품","📱 텔레그램 설정","📖 가이드"])

# ══════════════════════════════════════════════════════════════
# TAB 1: 라이브 검색
# ══════════════════════════════════════════════════════════════
with tab1:
    r1, r2, r3 = st.columns([1.2, 1.2, 2.6])
    with r1: main_cat = st.selectbox("대분류", list(CATEGORY_MAP.keys()), key="cat_main")
    with r2: st.selectbox("중분류", list(CATEGORY_MAP[main_cat].keys()), key="cat_sub")
    with r3: st.text_input("키워드", key="search_kw",
                            placeholder="예: 백팩, 무선이어폰...", on_change=do_live_search)

    b1, b2, b3, _ = st.columns([1.5, 1, 1.2, 2])
    with b1: st.button("검색", on_click=do_live_search, use_container_width=True, type="primary")
    with b2: st.button("초기화", on_click=reset_all, use_container_width=True)
    with b3:
        v_sel = st.selectbox("보기", ["표 보기","카드 보기"], key="live_view_sel",
                              label_visibility="collapsed")
        st.session_state["live_view"] = "card" if "카드" in v_sel else "table"

    if st.session_state.get("search_error"):
        st.warning(f"{st.session_state['search_error']}")

    if not st.session_state["show_results"]:
        st.markdown("""<div style="text-align:center;padding:3rem 0;color:#94a3b8">
            <div style="font-size:3rem">📦</div>
            <div style="font-size:1rem;margin-top:.5rem">키워드를 입력하고 검색하세요</div>
            <div style="font-size:.8rem;margin-top:.3rem">
                업체등급은 검색 후 자동 조회됩니다 (상위 15개 우선)</div>
        </div>""", unsafe_allow_html=True)
    else:
        raw_df = pd.DataFrame(st.session_state["live_results"])
        if raw_df.empty:
            st.info("검색 결과가 없습니다.")
        else:
            for col, default in [("seller_grade",""),("image_url","")]:
                if col not in raw_df.columns: raw_df[col] = default

            # ★ 업체등급 배치 조회 버튼 (상위 15개)
            grade_missing = (raw_df["seller_grade"]=="").sum() + (raw_df["seller_grade"].isna()).sum()
            if grade_missing > 0 and client:
                if st.button(f"업체등급 조회 ({min(15,grade_missing)}개 상세 API 호출 — 약 5~10초)",
                             use_container_width=True):
                    with st.spinner("업체등급 조회 중..."):
                        updated = client.batch_fetch_grades(raw_df.to_dict("records"), limit=15)
                        raw_df = pd.DataFrame(updated)
                        st.session_state["live_results"] = raw_df.to_dict("records")
                    st.rerun()

            site_counts = raw_df["site"].value_counts().to_dict()
            badge = " | ".join(f"{s} {n}개" for s, n in site_counts.items())
            st.markdown(f"<div style='color:#64748b;font-size:.85rem;margin-bottom:.5rem'>검색결과: {badge} / 총 {len(raw_df):,}개</div>",
                        unsafe_allow_html=True)

            fc1, fc2, fc3, fc4, fc5 = st.columns([2,1,1,1.2,1.2])
            with fc1: kw_filter = st.text_input("재검색","",placeholder="상품명 필터...",label_visibility="collapsed")
            with fc2: site_filter = st.selectbox("소싱처",["전체"]+list(site_counts.keys()),label_visibility="collapsed")
            with fc3: status_filter = st.selectbox("상태",["전체","정상만"],label_visibility="collapsed")
            with fc4: sort_col = st.selectbox("정렬",["예상 순수익(원)","공급가(원)","마진율(%)","추천 판매가(원)"],label_visibility="collapsed")
            with fc5: sort_order = st.selectbox("순서",["높은순","낮은순"],label_visibility="collapsed")

            df = apply_margin(raw_df, fee, margin)
            df["상태"] = df["status"].apply(lambda x: "🟢 정상" if str(x)=="Y" else "❌ 품절")
            if kw_filter: df = df[df["name"].str.contains(kw_filter, case=False, na=False)]
            if site_filter != "전체": df = df[df["site"]==site_filter]
            if status_filter == "정상만": df = df[df["status"]=="Y"]
            df = df.sort_values(sort_col, ascending=(sort_order=="낮은순"))

            ok_cnt = len(df[df["status"]=="Y"])
            avg_p  = int(df[df["status"]=="Y"]["예상 순수익(원)"].mean()) if ok_cnt>0 else 0
            max_p  = int(df["예상 순수익(원)"].max()) if len(df)>0 else 0

            k1, k2, k3, k4 = st.columns(4)
            k1.markdown(f'<div class="kpi-card"><div class="kpi-label">검색 결과</div><div class="kpi-value">{len(df):,}</div><div class="kpi-sub">개 상품</div></div>',unsafe_allow_html=True)
            k2.markdown(f'<div class="kpi-card"><div class="kpi-label">정상 판매</div><div class="kpi-value" style="color:#16a34a">{ok_cnt:,}</div><div class="kpi-sub">개</div></div>',unsafe_allow_html=True)
            k3.markdown(f'<div class="kpi-card"><div class="kpi-label">평균 순수익</div><div class="kpi-value">{avg_p:,}</div><div class="kpi-sub">원/건</div></div>',unsafe_allow_html=True)
            k4.markdown(f'<div class="kpi-card"><div class="kpi-label">최고 순수익</div><div class="kpi-value" style="color:#2563eb">{max_p:,}</div><div class="kpi-sub">원/건</div></div>',unsafe_allow_html=True)
            st.markdown("<br>",unsafe_allow_html=True)

            disp_size = 50 if st.session_state["live_view"]=="table" else 18
            total_pg  = max(1, (len(df)+disp_size-1)//disp_size)
            page_num  = min(st.session_state["page_num"], total_pg-1)
            page_df   = df.iloc[page_num*disp_size:(page_num+1)*disp_size].copy()
            tracked_ids = load_tracked_db()["product_id"].astype(str).tolist()
            page_df["⭐ 관심"] = page_df["product_id"].astype(str).isin(tracked_ids)

            if st.session_state["live_view"] == "card":
                render_cards(page_df, tracked_ids, id_prefix="live",
                             on_toggle=lambda p, t: do_track(p, t))
            else:
                show_cols = ["⭐ 관심","site","product_id","name","supply_price","delivery_fee",
                             "상태","추천 판매가(원)","예상 순수익(원)","마진율(%)","seller_grade"]
                disp = page_df[show_cols].copy()
                disp.columns = ["⭐ 관심","소싱업체","상품번호","상품명","공급가(원)",
                                "배송비(원)","상태","추천 판매가(원)","예상 순수익(원)","마진율(%)","업체등급"]
                edited = st.data_editor(disp, use_container_width=True, hide_index=True,
                    key=f"live_editor_{page_num}",
                    column_config={
                        "⭐ 관심":st.column_config.CheckboxColumn("⭐ 관심", width="small"),
                        "소싱업체":st.column_config.TextColumn("소싱업체", width="small"),
                        "상품번호":st.column_config.TextColumn("상품번호", width="small"),
                        "상품명":st.column_config.TextColumn("상품명", width="large"),
                        "공급가(원)":st.column_config.NumberColumn(format="%d원"),
                        "배송비(원)":st.column_config.NumberColumn(format="%d원"),
                        "추천 판매가(원)":st.column_config.NumberColumn(format="%d원"),
                        "예상 순수익(원)":st.column_config.NumberColumn(format="%d원"),
                        "마진율(%)":st.column_config.NumberColumn(format="%.1f%%"),
                        "업체등급":st.column_config.TextColumn("업체등급",
                            help="S>A>B>C>D>E 순 / 관심 등록 시 즉시 갱신"),
                    })
                any_changed = False
                for i in range(len(edited)):
                    if edited.iloc[i]["⭐ 관심"] != disp.iloc[i]["⭐ 관심"]:
                        prod = page_df.iloc[i].to_dict()
                        is_t = 1 if edited.iloc[i]["⭐ 관심"] else 0
                        do_track(prod, is_t); any_changed=True
                if any_changed: st.rerun()

            pn1, pn2, pn3 = st.columns([1,3,1])
            with pn1:
                if st.button("이전", disabled=(page_num==0), use_container_width=True):
                    st.session_state["page_num"]=page_num-1; st.rerun()
            with pn2:
                st.markdown(f"<div style='text-align:center;color:#64748b;font-size:.85rem;padding-top:.5rem'>"
                            f"{page_num+1}/{total_pg} | 총 {len(df):,}개</div>", unsafe_allow_html=True)
            with pn3:
                if st.button("다음", disabled=(page_num>=total_pg-1), use_container_width=True):
                    st.session_state["page_num"]=page_num+1; st.rerun()

# ══════════════════════════════════════════════════════════════
# TAB 2: 관심 상품
# ══════════════════════════════════════════════════════════════
with tab2:
    tracked_df = load_tracked_db()

    if tracked_df.empty:
        st.markdown("""<div style="text-align:center;padding:3rem 0;color:#94a3b8">
            <div style="font-size:3rem">⭐</div>
            <div style="font-size:1rem;margin-top:.5rem">관심 상품이 없습니다</div>
            <div style="font-size:.8rem">검색 탭에서 상품을 선택하면 저장됩니다</div>
        </div>""", unsafe_allow_html=True)
    else:
        total_m  = len(tracked_df)
        t_calc   = apply_margin(tracked_df, fee, margin)
        ok_m     = len(tracked_df[tracked_df["status"]=="Y"])
        avg_m    = round(t_calc["마진율(%)"].mean(), 1) if not t_calc.empty else 0
        avg_prof = int(t_calc[t_calc["status"]=="Y"]["예상 순수익(원)"].mean()) if ok_m>0 else 0
        monthly  = avg_prof * 100  # 월 100건 기준

        # ★ KPI: 품절 제거, 평균마진율/월예상수익 표시
        k1, k2, k3, k4 = st.columns(4)
        k1.markdown(f'<div class="kpi-card"><div class="kpi-label">관심 상품</div><div class="kpi-value">{total_m}</div><div class="kpi-sub">개 등록</div></div>',unsafe_allow_html=True)
        k2.markdown(f'<div class="kpi-card"><div class="kpi-label">정상 판매 가능</div><div class="kpi-value" style="color:#16a34a">{ok_m}</div><div class="kpi-sub">개</div></div>',unsafe_allow_html=True)
        k3.markdown(f'<div class="kpi-card"><div class="kpi-label">평균 마진율</div><div class="kpi-value" style="color:#7c3aed">{avg_m:.1f}%</div><div class="kpi-sub">목표마진 기준</div></div>',unsafe_allow_html=True)
        k4.markdown(f'<div class="kpi-card"><div class="kpi-label">월 예상수익 (100건 기준)</div><div class="kpi-value" style="color:#2563eb">{monthly:,}</div><div class="kpi-sub">원</div></div>',unsafe_allow_html=True)
        st.markdown("<br>", unsafe_allow_html=True)

        # 필터 + 보기 방식
        mv1, mv2, mv3 = st.columns([2,1,1])
        with mv1: m_filter = st.text_input("상품명 검색","",placeholder="검색...",label_visibility="collapsed")
        with mv2: m_status = st.selectbox("상태",["전체","정상만","품절만"],label_visibility="collapsed")
        with mv3:
            mv_sel = st.selectbox("보기",["표 보기","카드 보기"],key="mon_view_sel",label_visibility="collapsed")
            st.session_state["mon_view"] = "card" if "카드" in mv_sel else "table"

        mdf = t_calc.copy()
        mdf["상태"] = mdf["status"].apply(lambda x: "🟢 정상" if str(x)=="Y" else "❌ 품절")
        for col, default in [("seller_grade",""),("image_url","")]:
            if col not in mdf.columns: mdf[col]=default
        mdf["seller_grade"] = mdf["seller_grade"].fillna("").replace("nan","")
        if m_filter: mdf = mdf[mdf["name"].str.contains(m_filter, case=False, na=False)]
        if m_status == "정상만": mdf = mdf[mdf["status"]=="Y"]
        elif m_status == "품절만": mdf = mdf[mdf["status"]!="Y"]

        tracked_ids_m = mdf["product_id"].astype(str).tolist()

        edited_m = None  # AI 선택용

        if st.session_state["mon_view"] == "card":
            render_cards(mdf, tracked_ids_m, id_prefix="mon",
                         on_toggle=lambda p, t: (upsert_tracked_product(p, t), st.rerun()))
        else:
            # 표 보기
            mdf["AI선택"] = False
            mdf["해제"]   = True
            if "updated_at" in mdf.columns:
                mdf["등록일"] = mdf["updated_at"].apply(fmt_dt)

            keep = ["AI선택","해제","site","product_id","name","supply_price","delivery_fee",
                    "상태","추천 판매가(원)","예상 순수익(원)","마진율(%)","seller_grade","등록일"]
            mdf_disp = mdf[[c for c in keep if c in mdf.columns]].copy()
            mdf_disp = mdf_disp.rename(columns={
                "site":"소싱업체","product_id":"상품번호","name":"상품명",
                "supply_price":"공급가(원)","delivery_fee":"배송비(원)","seller_grade":"업체등급"})

            edited_m = st.data_editor(mdf_disp, use_container_width=True, hide_index=True,
                key="tracked_editor",
                column_config={
                    "AI선택": st.column_config.CheckboxColumn("AI선택", width="small",
                        help="체크한 상품만 AI 분석"),
                    "해제": st.column_config.CheckboxColumn("해제", default=True, width="small"),
                    "소싱업체": st.column_config.TextColumn("소싱업체", width="small"),
                    "상품번호": st.column_config.TextColumn("상품번호", width="small"),
                    "상품명":   st.column_config.TextColumn("상품명", width="large"),
                    "공급가(원)": st.column_config.NumberColumn(format="%d원"),
                    "배송비(원)": st.column_config.NumberColumn(format="%d원"),
                    "추천 판매가(원)": st.column_config.NumberColumn(format="%d원"),
                    "예상 순수익(원)": st.column_config.NumberColumn(format="%d원"),
                    "마진율(%)": st.column_config.NumberColumn(format="%.1f%%"),
                    "업체등급": st.column_config.TextColumn("업체등급",
                        help="S>A>B>C>D>E / 관심 등록 시 갱신"),
                    "등록일": st.column_config.TextColumn("등록일",
                        help="소싱레이더 DB 저장 기준 (업체 변경 시간 아님)"),
                },
                disabled=[c for c in mdf_disp.columns if c not in ["AI선택","해제"]],
            )

            track_changed = False
            for i in range(len(edited_m)):
                if not edited_m.iloc[i]["해제"]:
                    upsert_tracked_product(mdf.iloc[i].to_dict(), 0)
                    track_changed = True
            if track_changed: st.rerun()

        st.markdown("<br>", unsafe_allow_html=True)

        # 텔레그램 전송 — ★ 카드/표 모두 동일한 컨테이너에서 처리
        tg_col1, tg_col2 = st.columns([3,1])
        with tg_col1:
            tg_btn = st.button("관심 상품 현황 텔레그램 전송", use_container_width=True)
        with tg_col2:
            pass  # 레이아웃용

        if tg_btn:
            lines = [f"관심 상품 현황\n전체 {total_m}개 / 정상 {ok_m}개 / 평균마진 {avg_m:.1f}%\n"]
            for _, row in t_calc.iterrows():
                icon = "O" if row["status"]=="Y" else "X"
                lines.append(
                    f"{icon} {row['name'][:22]} 판매가{int(row['추천 판매가(원)']):,}원 "
                    f"수익{int(row['예상 순수익(원)']):,}원"
                )
            ok_sent = send_tg_long("\n".join(lines), "관심 상품 현황")
            if ok_sent:
                st.success("전송 완료")
            else:
                st.error("전송 실패. 텔레그램 설정을 확인하세요.")

        # ── AI 소싱 분석 ──────────────────────────────────────
        st.markdown("---")
        st.markdown("#### AI 소싱 분석")

        if not GEMINI_KEY:
            st.info("aistudio.google.com 에서 무료 API 키 발급 후 Secrets에 GEMINI_API_KEY 등록")
        else:
            sel_count = 0
            sel_df    = pd.DataFrame()

            if edited_m is not None and "AI선택" in edited_m.columns:
                sel_rows  = edited_m[edited_m["AI선택"]==True]
                sel_count = len(sel_rows)
                if sel_count > 0:
                    sel_names = sel_rows["상품명"].tolist()
                    sel_df    = t_calc[t_calc["name"].isin(sel_names)].copy()

            if sel_count > 0:
                st.success(f"{sel_count}개 선택됨")
            elif st.session_state["mon_view"] == "table":
                st.info("표에서 AI선택 체크 후 분석하거나, 전체 분석 버튼을 사용하세요.")

            btn1, btn2 = st.columns([2,1])
            with btn1:
                ai_sel_btn = st.button("선택 상품 AI 분석", type="primary",
                                       use_container_width=True, disabled=(sel_count==0))
            with btn2:
                ai_all_btn = st.button("전체 AI 분석", use_container_width=True)

            if ai_all_btn:
                with st.spinner(f"전체 {total_m}개 분석 중..."):
                    result = compact_ai(t_calc, fee, margin, platform_name, margin_name)
                st.session_state["ai_result"] = result

            if ai_sel_btn and sel_count > 0:
                target = apply_margin(sel_df, fee, margin)
                with st.spinner(f"{sel_count}개 분석 중..."):
                    result = compact_ai(target, fee, margin, platform_name, margin_name)
                st.session_state["ai_result"] = result

            if st.session_state.get("ai_result"):
                st.markdown("---")
                st.markdown("**AI 소싱 분석 결과**")
                result_text = st.session_state["ai_result"]
                st.markdown(result_text)
                st.markdown("<br>", unsafe_allow_html=True)

                tg2, clr = st.columns([2,1])
                with tg2:
                    if st.button("분석 결과 텔레그램 전송", use_container_width=True, key="ai_tg"):
                        ok_sent = send_tg_long(result_text, "AI 소싱 분석")
                        if ok_sent:
                            st.success("전송 완료")
                        else:
                            st.error("전송 실패")
                with clr:
                    if st.button("결과 초기화", use_container_width=True, key="ai_clr"):
                        st.session_state["ai_result"] = None; st.rerun()

# ══════════════════════════════════════════════════════════════
# TAB 3: 텔레그램 설정
# ══════════════════════════════════════════════════════════════
with tab3:
    st.markdown("### 텔레그램 알림 설정")
    col_a, col_b = st.columns(2)
    with col_a:
        st.markdown("""
봇 만들기
1. 텔레그램에서 @BotFather 검색
2. /newbot 입력 후 이름 설정
3. 발급된 토큰 복사

채팅방 ID 확인
브라우저에서 아래 주소 접속:
https://api.telegram.org/bot[토큰]/getUpdates
chat.id 뒤 숫자가 채팅방 ID
        """)
    with col_b:
        st.markdown("Secrets 등록")
        st.code("""DOMEGGOOK_API_KEY  = "API키"
TELEGRAM_BOT_TOKEN = "봇토큰"
TELEGRAM_CHAT_ID   = "채팅방ID"
GEMINI_API_KEY     = "제미나이키(무료)"
ONCHANNEL_ID       = "온채널ID(선택)"
ONCHANNEL_PW       = "온채널PW(선택)"
""", language="toml")
        test_msg = st.text_input("테스트 메시지", value="소싱레이더 연동 테스트")
        if st.button("테스트 발송", type="primary", use_container_width=True):
            ok = send_telegram_message(test_msg)
            st.success("성공") if ok else st.error("실패")

# ══════════════════════════════════════════════════════════════
# TAB 4: 가이드
# ══════════════════════════════════════════════════════════════
with tab4:
    st.markdown("### 가이드")
    with st.expander("업체등급 표시 방식"):
        st.markdown("""
도매매/도매꾹 목록 API에는 업체등급 정보가 포함되지 않습니다.
등급을 확인하는 방법은 두 가지입니다.

1. 검색 결과 화면에서 업체등급 조회 버튼 클릭 (상위 15개 자동 조회)
2. 관심 등록 시 즉시 해당 상품 상세 API를 호출해서 등급 갱신

온채널은 별도 등급 체계를 사용합니다.
        """)
    with st.expander("온채널 연동 방법"):
        st.markdown("""
온채널은 비로그인 상태에서는 자동화 접근이 차단됩니다.
로그인 계정이 있어야 크롤링이 가능합니다.

Secrets에 아래 두 줄 추가:
ONCHANNEL_ID = "온채널아이디"
ONCHANNEL_PW = "온채널비밀번호"

등록 후 소싱 업체에서 온채널을 선택하면 로그인 후 검색합니다.
        """)
    with st.expander("업체 등급 기준 (도매매/도매꾹)"):
        st.markdown("""
S등급 최우수 강력 권장
A등급 우수 권장
B등급 양호 무난
C등급 보통 검토 필요
D등급 미흡 신중 검토
E등급 불량 비권장

B등급 이상 공급사 소싱을 권장합니다.
관심 등록 시 상세 API 호출로 실제 등급이 자동 저장됩니다.
        """)
    with st.expander("마진 계산 공식"):
        st.markdown("""
추천 판매가 = (공급가 + 배송비) 나누기 (1 빼기 수수료율 빼기 마진율)
예상 순수익 = 판매가 빼기 (판매가 곱하기 수수료율) 빼기 공급가 빼기 배송비
        """)
    with st.expander("AI 분석 출력 항목"):
        st.markdown("""
즉시 소싱 추천 TOP3
제외 권장 상품
개별 판정 (추천도 / 마진경쟁력 / 리스크 / 월수익)
이번달 소싱 전략 3가지
공통 주의사항

텔레그램 전송 시 글자 수 초과 시 자동 분할 발송합니다.
        """)
