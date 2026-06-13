import streamlit as st
import sqlite3
import pandas as pd
import requests as req
from utils import calculate_target_price, calculate_expected_profit
from database import init_db, upsert_tracked_product
from domeme_client import DomeameClient
from notifications import send_telegram_message

try:
    from onchannel_client import OnchannelClient
    OC_AVAILABLE = True
except ImportError:
    OC_AVAILABLE = False

# ── 페이지 설정 ──────────────────────────────────────────────
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
.kpi-label{font-size:.75rem;color:#64748b;font-weight:600;text-transform:uppercase;
    letter-spacing:.05em;margin-bottom:.3rem}
.kpi-value{font-size:1.8rem;font-weight:700;color:#1e293b;line-height:1}
.kpi-sub{font-size:.75rem;color:#94a3b8;margin-top:.2rem}
.prod-card{background:white;border:1px solid #e2e8f0;border-radius:10px;
    padding:.8rem;margin-bottom:.5rem;display:flex;gap:.8rem;align-items:flex-start}
.prod-img{width:80px;height:80px;object-fit:cover;border-radius:6px;
    border:1px solid #f1f5f9;flex-shrink:0;background:#f8fafc}
.prod-img-placeholder{width:80px;height:80px;border-radius:6px;background:#f1f5f9;
    display:flex;align-items:center;justify-content:center;font-size:1.5rem;flex-shrink:0}
.prod-info{flex:1;min-width:0}
.prod-name{font-size:.85rem;font-weight:500;color:#1e293b;
    white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.prod-meta{font-size:.75rem;color:#64748b;margin-top:.2rem}
.prod-profit{font-size:.9rem;font-weight:700;color:#2563eb}
.grade-s{color:#f59e0b;font-weight:600} .grade-a{color:#3b82f6;font-weight:600}
.grade-b{color:#22c55e;font-weight:600} .grade-c{color:#eab308;font-weight:600}
.grade-d{color:#f97316;font-weight:600} .grade-e{color:#ef4444;font-weight:600}
section[data-testid="stSidebar"]{background:#1a1a2e !important}
section[data-testid="stSidebar"] *{color:#cbd5e1 !important}
.stButton>button{border-radius:8px !important;font-weight:600 !important;transition:all .2s !important}
.stTabs [data-baseweb="tab-list"]{gap:4px;background:#f1f5f9;border-radius:10px;padding:4px}
.stTabs [data-baseweb="tab"]{border-radius:8px !important;font-weight:500 !important}
.stTabs [aria-selected="true"]{background:white !important;box-shadow:0 1px 3px rgba(0,0,0,.1) !important}
footer{visibility:hidden}
</style>
""", unsafe_allow_html=True)

# ── Secrets / 클라이언트 초기화 ──────────────────────────────
try:
    DOME_KEY   = st.secrets["DOMEGGOOK_API_KEY"]
    GEMINI_KEY = st.secrets.get("GEMINI_API_KEY", "")
    OC_ID      = st.secrets.get("ONCHANNEL_ID", "")
    OC_PW      = st.secrets.get("ONCHANNEL_PW", "")
except Exception:
    DOME_KEY = GEMINI_KEY = OC_ID = OC_PW = ""

init_db()
client    = DomeameClient(api_key=DOME_KEY) if DOME_KEY else None
oc_client = OnchannelClient(user_id=OC_ID, password=OC_PW) if OC_AVAILABLE else None

# ── 상수 ─────────────────────────────────────────────────────
CATEGORY_MAP = {
    "전체보기":{"전체보기":"0000"},
    "패션의류":{"전체보기":"01","여성의류":"0101","남성의류":"0102","언더웨어":"0103"},
    "패션잡화":{"전체보기":"02","신발":"0201","가방":"0202","화장품/미용":"0204"},
    "디지털/가전":{"전체보기":"04","음향가전":"0401","생활가전":"0402","계절가전":"0403"},
    "생활/건강":{"전체보기":"06","생활용품":"0601","건강/의료용품":"0602"},
    "식품":{"전체보기":"09","가공식품":"0901","건강식품":"0902","농축수산물":"0903"},
    "가구/인테리어":{"전체보기":"10","가구":"1001","인테리어소품":"1002"},
}
PLATFORM_FEE = {"네이버 스마트스토어":0.08,"쿠팡":0.11,"지마켓/옥션":0.14}
MARGIN_MAP   = {"안정형  (10%)":0.10,"밸런스형 (20%)":0.20,"고마진형 (40%)":0.40}
FETCH_PRESETS= {"빠른 탐색  (50개)":(50,1),"일반 검색  (100개)":(50,2),
                "심층 분석  (200개)":(50,4),"대량 수집  (500개)":(50,10)}

# ── 세션 초기화 ──────────────────────────────────────────────
for k,v in {"live_results":[],"show_results":False,"search_error":None,
            "page_num":0,"ai_result":None,"view_mode":"table"}.items():
    if k not in st.session_state:
        st.session_state[k]=v

# ── 헬퍼 ─────────────────────────────────────────────────────
def load_tracked_db():
    try:
        conn=sqlite3.connect("sourcing.db")
        df=pd.read_sql_query("SELECT * FROM products WHERE is_tracked=1 ORDER BY updated_at DESC",conn)
        conn.close()
        for col,default in [("seller_grade",""),("image_url","")]:
            if col not in df.columns:
                df[col]=default
        return df
    except Exception as e:
        st.error(f"DB 오류: {e}"); return pd.DataFrame()

def apply_margin(df,fee,margin):
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

    results=[]
    errors=[]

    if any(s in sites for s in ["도매매","도매꾹"]):
        if not DOME_KEY:
            errors.append("도매매/도매꾹 API 키 없음")
        elif client:
            try:
                if "도매매" in sites:
                    results.extend(client.fetch_product_list(market="supply",keyword=kw,category_code=cat,page_size=pg_size,max_pages=max_pg))
                if "도매꾹" in sites:
                    results.extend(client.fetch_product_list(market="dome",keyword=kw,category_code=cat,page_size=pg_size,max_pages=max_pg))
            except Exception as e:
                errors.append(f"도매매/도매꾹 오류: {e}")

    if "온채널" in sites and oc_client:
        if not OC_ID or not OC_PW:
            errors.append("온채널 ID/PW 미설정")
        elif kw:
            try:
                oc=oc_client.fetch_product_list(keyword=kw,page_size=pg_size*max_pg,max_pages=max_pg)
                results.extend(oc)
            except Exception as e:
                errors.append(f"온채널 오류: {e}")

    if errors:
        st.session_state["search_error"]=" | ".join(errors)
    if not results and not errors:
        st.session_state["search_error"]="검색 결과 없음"
    elif results:
        df=pd.DataFrame(results).drop_duplicates(subset=["product_id"])
        for col,default in [("seller_grade","조회중"),("image_url","")]:
            if col not in df.columns: df[col]=default
        st.session_state["live_results"]=df.to_dict("records")
    st.session_state["show_results"]=True

def reset_all():
    st.session_state.update({"search_kw":"","live_results":[],"show_results":False,
                              "search_error":None,"page_num":0,"ai_result":None})
    st.rerun()

def expert_ai_analyze(items_df, fee, margin, platform_name, margin_name):
    """Gemini 전문 소싱 분석 — 상세 프롬프트"""
    if not GEMINI_KEY:
        return "GEMINI_API_KEY 미설정"

    rows=[]
    for _,r in items_df.iterrows():
        profit      = int(r.get("예상 순수익(원)",0))
        sale_price  = int(r.get("추천 판매가(원)",0))
        supply      = int(r.get("supply_price",0))
        delivery    = int(r.get("delivery_fee",0))
        margin_pct  = float(r.get("마진율(%)",0))
        grade       = r.get("seller_grade","미확인") or "미확인"
        status      = "정상" if r.get("status","Y")=="Y" else "품절"
        monthly_50  = profit * 50
        monthly_100 = profit * 100
        price_room  = sale_price * 0.1  # 10% 가격 인하 여유

        rows.append(
            f"━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
            f"상품명: {r['name'][:45]}\n"
            f"소싱처: {r.get('site','')} | 상품번호: {r.get('product_id','')}\n"
            f"공급가: {supply:,}원 | 배송비: {delivery:,}원 | 원가합계: {supply+delivery:,}원\n"
            f"추천판매가: {sale_price:,}원 | 예상순수익: {profit:,}원/건 | 마진율: {margin_pct:.1f}%\n"
            f"월50건수익: {monthly_50:,}원 | 월100건수익: {monthly_100:,}원\n"
            f"가격인하여유(10%): {int(price_room):,}원 | 재고상태: {status}\n"
            f"업체등급: {grade}"
        )

    prompt = f"""당신은 이커머스 도매 소싱 분야 20년 경력의 최고 전문가입니다.
아래 관심 상품들을 아래 기준으로 철저하게 분석해주세요.
단순한 수치 나열이 아니라, 실제 소싱 의사결정에 바로 활용할 수 있는 전문가 판단을 제시해야 합니다.

[현재 판매 설정]
플랫폼: {platform_name} | 수수료: {int(fee*100)}% | 마진전략: {margin_name}({int(margin*100)}%)

[분석 대상]
{chr(10).join(rows)}

━━━━━━━━━━━━━━━━━━━━━━━━━━

## 📊 개별 상품 심층 분석

각 상품마다 아래 모든 항목을 작성하세요:

**[상품명]**

🎯 **소싱 판정**: ✅ 강력추천 / 👍 추천 / ⚠️ 주의 / ❌ 비추천
*(판정 이유를 한 문장으로)*

💰 **마진 경쟁력 분석**
- 현재 마진율 {margin_pct if rows else 0:.0f}%가 해당 카테고리 온라인 평균 대비 어느 수준인지
- 최저가 경쟁 시 마진율이 몇 %까지 떨어질 수 있는지
- 광고비(CPC) 10~15% 투입 시 실제 순수익은 얼마인지

📦 **수익 시나리오**
- 낙관적 (월 150건): 예상 월 순수익
- 보수적 (월 50건): 예상 월 순수익
- 손익분기점: 월 최소 몇 건 판매 시 수익 발생

🏢 **업체 신뢰도 평가**
- 등급 기반 리스크 수준 (S/A=저위험, B=중간, C이하=고위험)
- 품질 불량/배송 지연/갑작스러운 단종 발생 가능성
- 거래 전 확인 권장 사항

⚡ **시장 경쟁 분석**
- 네이버·쿠팡 내 동일/유사 상품 경쟁 강도 예상
- 차별화 가능 포인트 (번들·사은품·상세페이지 퀄리티 등)
- 계절성·트렌드 의존도

⚠️ **핵심 리스크**
*(가장 중요한 리스크 1~2가지만, 구체적으로)*

💡 **전략적 제안**
*(즉시 실행 가능한 행동 방안 2가지)*

---

## 🏆 포트폴리오 종합 평가

**즉시 소싱 권장 TOP 순위** (순위 + 이유)

**제외 권장 상품** (이유 포함)

**포트폴리오 다각화 진단**
- 카테고리 편중 여부
- 리스크 분산 점수 (10점 만점)

**이번 달 소싱 전략 제언**
*(3가지 구체적 액션 플랜)*

한국어로 작성. 수치 근거 필수. 모호한 표현 금지."""

    try:
        resp=req.post(
            f"https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash-lite:generateContent?key={GEMINI_KEY}",
            headers={"Content-Type":"application/json"},
            json={"contents":[{"parts":[{"text":prompt}]}],
                  "generationConfig":{"maxOutputTokens":4000,"temperature":0.15}},
            timeout=90,
        )
        if resp.status_code==200:
            return resp.json()["candidates"][0]["content"]["parts"][0]["text"]
        return f"Gemini 오류 {resp.status_code}: {resp.text[:300]}"
    except Exception as e:
        return f"AI 연결 오류: {e}"

# ── 사이드바 ─────────────────────────────────────────────────
with st.sidebar:
    st.markdown("## 📡 소싱레이더")
    st.markdown("---")
    st.markdown("#### 🏪 소싱 설정")

    site_opts=["도매매","도매꾹"]
    if OC_AVAILABLE: site_opts.append("온채널")
    sourcing_sites=st.multiselect("소싱 업체",options=site_opts,
                                   default=["도매매","도매꾹"],key="sourcing_sites")
    if OC_AVAILABLE:
        oc_st="✅ 연동됨" if (OC_ID and OC_PW) else "⚠️ ID/PW 미설정"
        st.caption(f"온채널: {oc_st}")

    fetch_preset=st.selectbox("검색 수량",list(FETCH_PRESETS.keys()),index=1,key="fetch_preset")
    st.markdown("#### 💰 판매 전략")
    platform_name=st.selectbox("판매 플랫폼",list(PLATFORM_FEE.keys()))
    margin_name=st.select_slider("마진 전략",options=list(MARGIN_MAP.keys()))
    fee=PLATFORM_FEE[platform_name]; margin=MARGIN_MAP[margin_name]

    st.markdown(f"""<div style="background:#0f3460;border-radius:10px;padding:.8rem 1rem;margin-top:.5rem">
        <div style="color:#94a3b8;font-size:.72rem;font-weight:600">현재 설정</div>
        <div style="color:white;font-size:1rem;font-weight:700;margin-top:.2rem">
            수수료 {int(fee*100)}% | 목표마진 {int(margin*100)}%</div>
        <div style="color:#64748b;font-size:.72rem;margin-top:.2rem">배수 ÷{round(1-fee-margin,2)}</div>
    </div>""",unsafe_allow_html=True)
    st.markdown("---")

    t_df=load_tracked_db()
    total_t=len(t_df)
    oos_t=len(t_df[t_df["status"]!="Y"]) if not t_df.empty else 0
    st.markdown("#### 📊 관심 상품")
    c1,c2=st.columns(2); c1.metric("전체",total_t); c2.metric("❌ 품절",oos_t)
    st.markdown("---")
    st.markdown("#### 📱 텔레그램")
    try: tg_ok=st.secrets.get("TELEGRAM_BOT_TOKEN","") not in ["","봇토큰_입력"]
    except: tg_ok=False
    st.markdown(f"상태: {'✅ 연동됨' if tg_ok else '⚠️ 미설정'}")
    if st.button("🔔 테스트 발송",use_container_width=True):
        ok=send_telegram_message(f"✅ 소싱레이더 연동 테스트!\n관심 상품: {total_t}개")
        st.success("발송!") if ok else st.error("실패")
    st.markdown("---")
    st.markdown(f"#### 🤖 AI 분석\n{'✅ Gemini 사용 가능' if GEMINI_KEY else '⚠️ GEMINI_API_KEY 미설정'}")
    st.markdown("---")
    st.caption("소싱레이더 v5.0")

# ── 헤더 ────────────────────────────────────────────────────
st.markdown("""<div class="main-header">
    <h1>📡 소싱레이더</h1>
    <p>도매매 · 도매꾹 · 온채널 실시간 통합 마진 분석 시스템</p>
</div>""",unsafe_allow_html=True)

tab_search,tab_monitor,tab_telegram,tab_guide=st.tabs([
    "🔍 라이브 검색","⭐ 관심 상품","📱 텔레그램 설정","📖 가이드"])

# ══════════════════════════════════════════════════════════════
# TAB 1: 라이브 검색
# ══════════════════════════════════════════════════════════════
with tab_search:
    col1,col2,col3=st.columns([1.2,1.2,2.6])
    with col1: main_cat=st.selectbox("대분류",list(CATEGORY_MAP.keys()),key="cat_main")
    with col2: st.selectbox("중분류",list(CATEGORY_MAP[main_cat].keys()),key="cat_sub")
    with col3: st.text_input("🔎 상품 키워드",key="search_kw",
                              placeholder="예: 백팩, 무선이어폰...",on_change=do_live_search)
    b1,b2,b3,_=st.columns([1.5,1,1,2])
    with b1: st.button("🔍 검색",on_click=do_live_search,use_container_width=True,type="primary")
    with b2: st.button("🔄 초기화",on_click=reset_all,use_container_width=True)
    with b3:
        view_mode=st.selectbox("보기 방식",["📋 표","🖼 카드"],
                                key="view_mode_sel",label_visibility="collapsed")
        st.session_state["view_mode"]="table" if "표" in view_mode else "card"

    if st.session_state.get("search_error"):
        st.warning(f"⚠️ {st.session_state['search_error']}")

    if not st.session_state["show_results"]:
        st.markdown("""<div style="text-align:center;padding:3rem 0;color:#94a3b8">
            <div style="font-size:3rem">📦</div>
            <div style="font-size:1rem;margin-top:.5rem">키워드를 입력하고 검색하세요</div>
            <div style="font-size:.85rem;margin-top:.3rem">표 보기 / 카드+이미지 보기 선택 가능</div>
        </div>""",unsafe_allow_html=True)
    else:
        raw_df=pd.DataFrame(st.session_state["live_results"])
        if raw_df.empty:
            st.info("검색 결과가 없습니다.")
        else:
            for col,default in [("seller_grade","조회중"),("image_url","")]:
                if col not in raw_df.columns: raw_df[col]=default

            site_counts=raw_df["site"].value_counts().to_dict()
            badge=" | ".join(f"**{s}** {n}개" for s,n in site_counts.items())
            st.markdown(f"<div style='color:#64748b;font-size:.85rem;margin-bottom:.5rem'>📊 {badge} | 총 {len(raw_df):,}개</div>",unsafe_allow_html=True)

            fc1,fc2,fc3,fc4,fc5=st.columns([2,1,1,1.2,1.2])
            with fc1: kw_filter=st.text_input("재검색","",placeholder="상품명 필터...",label_visibility="collapsed")
            with fc2: site_filter=st.selectbox("소싱처",["전체"]+list(site_counts.keys()),label_visibility="collapsed")
            with fc3: status_filter=st.selectbox("상태",["전체","정상만"],label_visibility="collapsed")
            with fc4: sort_col=st.selectbox("정렬",["예상 순수익(원)","공급가(원)","마진율(%)","추천 판매가(원)"],label_visibility="collapsed")
            with fc5: sort_order=st.selectbox("순서",["높은순","낮은순"],label_visibility="collapsed")

            df=apply_margin(raw_df,fee,margin)
            df["상태"]=df["status"].apply(lambda x:"🟢 정상" if str(x)=="Y" else "❌ 품절")

            if kw_filter: df=df[df["name"].str.contains(kw_filter,case=False,na=False)]
            if site_filter!="전체": df=df[df["site"]==site_filter]
            if status_filter=="정상만": df=df[df["status"]=="Y"]
            df=df.sort_values(sort_col,ascending=(sort_order=="낮은순"))

            ok_cnt=len(df[df["status"]=="Y"])
            avg_p=int(df[df["status"]=="Y"]["예상 순수익(원)"].mean()) if ok_cnt>0 else 0
            max_p=int(df["예상 순수익(원)"].max()) if len(df)>0 else 0

            k1,k2,k3,k4=st.columns(4)
            k1.markdown(f'<div class="kpi-card"><div class="kpi-label">검색 결과</div><div class="kpi-value">{len(df):,}</div><div class="kpi-sub">개 상품</div></div>',unsafe_allow_html=True)
            k2.markdown(f'<div class="kpi-card"><div class="kpi-label">정상 판매</div><div class="kpi-value" style="color:#16a34a">{ok_cnt:,}</div><div class="kpi-sub">개</div></div>',unsafe_allow_html=True)
            k3.markdown(f'<div class="kpi-card"><div class="kpi-label">평균 순수익</div><div class="kpi-value">{avg_p:,}</div><div class="kpi-sub">원</div></div>',unsafe_allow_html=True)
            k4.markdown(f'<div class="kpi-card"><div class="kpi-label">최고 순수익</div><div class="kpi-value" style="color:#2563eb">{max_p:,}</div><div class="kpi-sub">원</div></div>',unsafe_allow_html=True)
            st.markdown("<br>",unsafe_allow_html=True)

            disp_size=50 if st.session_state["view_mode"]=="table" else 20
            total_pg=max(1,(len(df)+disp_size-1)//disp_size)
            page_num=min(st.session_state["page_num"],total_pg-1)
            page_df=df.iloc[page_num*disp_size:(page_num+1)*disp_size].copy()

            tracked_ids=load_tracked_db()["product_id"].astype(str).tolist()
            page_df["⭐ 관심"]=page_df["product_id"].astype(str).isin(tracked_ids)

            # ── 카드 보기 (이미지 포함) ──────────────────────
            if st.session_state["view_mode"]=="card":
                st.caption("💡 업체등급 '조회중' → ⭐ 관심 등록 시 실제 등급 자동 갱신")
                cols_per_row=3
                rows_list=[page_df.iloc[i:i+cols_per_row] for i in range(0,len(page_df),cols_per_row)]
                for row_group in rows_list:
                    card_cols=st.columns(cols_per_row)
                    for ci,(idx,row) in enumerate(row_group.iterrows()):
                        with card_cols[ci]:
                            grade=str(row.get("seller_grade","")).strip()
                            img_url=str(row.get("image_url","")).strip()
                            profit=int(row["예상 순수익(원)"])
                            sale=int(row["추천 판매가(원)"])
                            is_tracked=row["⭐ 관심"]

                            # 이미지
                            if img_url and img_url.startswith("http"):
                                try:
                                    st.image(img_url,width=200)
                                except Exception:
                                    st.markdown("🖼",unsafe_allow_html=False)
                            else:
                                st.markdown("<div style='height:120px;background:#f1f5f9;border-radius:8px;display:flex;align-items:center;justify-content:center;font-size:2rem;margin-bottom:8px'>📦</div>",unsafe_allow_html=True)

                            grade_color={"S":"#f59e0b","A":"#3b82f6","B":"#22c55e",
                                         "C":"#eab308","D":"#f97316","E":"#ef4444"}.get(
                                grade[0].upper() if grade and grade[0].isalpha() else "","#94a3b8")

                            st.markdown(f"""
                            <div style="font-size:.8rem;font-weight:500;color:#1e293b;margin-bottom:4px;
                                white-space:nowrap;overflow:hidden;text-overflow:ellipsis" title="{row['name']}">
                                {row['name'][:35]}
                            </div>
                            <div style="font-size:.72rem;color:#64748b;margin-bottom:4px">
                                {row.get('site','')} | {row.get('product_id','')}
                            </div>
                            <div style="font-size:.72rem;margin-bottom:2px">
                                공급가 <b>{int(row['supply_price']):,}원</b>
                                배송비 <b>{int(row['delivery_fee']):,}원</b>
                            </div>
                            <div style="font-size:.85rem;font-weight:700;color:#2563eb">
                                판매가 {sale:,}원 | 순수익 {profit:,}원
                            </div>
                            <div style="font-size:.72rem;margin-top:2px">
                                마진율 <b>{row['마진율(%)']:.1f}%</b> |
                                등급 <span style="color:{grade_color};font-weight:600">{grade or '조회중'}</span> |
                                {row['상태']}
                            </div>
                            """,unsafe_allow_html=True)

                            # 관심 등록 버튼
                            btn_label="⭐ 등록됨" if is_tracked else "☆ 관심 등록"
                            btn_type="secondary" if is_tracked else "primary"
                            if st.button(btn_label,key=f"card_btn_{idx}",
                                         use_container_width=True):
                                prod=row.to_dict()
                                is_track=0 if is_tracked else 1
                                if is_track and client and prod.get("site") in ["도매매","도매꾹"]:
                                    detail=client.fetch_item_detail(str(prod["product_id"]))
                                    if detail:
                                        prod.update({k:v for k,v in detail.items() if v})
                                upsert_tracked_product(prod,is_track)
                                st.rerun()

            # ── 표 보기 ──────────────────────────────────────
            else:
                st.caption("💡 업체등급 '조회중' → ⭐ 관심 등록 시 실제 등급 자동 갱신")
                show_cols=["⭐ 관심","site","product_id","name","supply_price","delivery_fee",
                           "상태","추천 판매가(원)","예상 순수익(원)","마진율(%)","seller_grade"]
                disp=page_df[show_cols].copy()
                disp.columns=["⭐ 관심","소싱업체","상품번호","상품명","공급가(원)",
                              "배송비(원)","상태","추천 판매가(원)","예상 순수익(원)","마진율(%)","업체등급"]

                edited=st.data_editor(disp,use_container_width=True,hide_index=True,
                    key=f"live_editor_{page_num}",
                    column_config={
                        "⭐ 관심":st.column_config.CheckboxColumn("⭐ 관심",width="small"),
                        "소싱업체":st.column_config.TextColumn("소싱업체",width="small"),
                        "상품번호":st.column_config.TextColumn("상품번호",width="small"),
                        "상품명":st.column_config.TextColumn("상품명",width="large"),
                        "공급가(원)":st.column_config.NumberColumn(format="%d원"),
                        "배송비(원)":st.column_config.NumberColumn(format="%d원"),
                        "추천 판매가(원)":st.column_config.NumberColumn(format="%d원"),
                        "예상 순수익(원)":st.column_config.NumberColumn(format="%d원"),
                        "마진율(%)":st.column_config.NumberColumn(format="%.1f%%"),
                        "업체등급":st.column_config.TextColumn("업체등급",
                            help="⭐S>🔵A>🟢B>🟡C>🟠D>🔴E | 관심 등록 시 자동 갱신"),
                    })

                any_changed=False
                for i in range(len(edited)):
                    if edited.iloc[i]["⭐ 관심"]!=disp.iloc[i]["⭐ 관심"]:
                        prod=page_df.iloc[i].to_dict()
                        is_track=1 if edited.iloc[i]["⭐ 관심"] else 0
                        if is_track and client and prod.get("site") in ["도매매","도매꾹"]:
                            detail=client.fetch_item_detail(str(prod["product_id"]))
                            if detail:
                                for k,v in detail.items():
                                    if v: prod[k]=v
                        upsert_tracked_product(prod,is_track)
                        any_changed=True
                if any_changed: st.rerun()

            # 페이지 이동
            pn1,pn2,pn3=st.columns([1,3,1])
            with pn1:
                if st.button("◀ 이전",disabled=(page_num==0),use_container_width=True):
                    st.session_state["page_num"]=page_num-1; st.rerun()
            with pn2:
                st.markdown(f"<div style='text-align:center;color:#64748b;font-size:.85rem;padding-top:.5rem'>"
                            f"{page_num+1} / {total_pg} 페이지 | 총 {len(df):,}개</div>",unsafe_allow_html=True)
            with pn3:
                if st.button("다음 ▶",disabled=(page_num>=total_pg-1),use_container_width=True):
                    st.session_state["page_num"]=page_num+1; st.rerun()

# ══════════════════════════════════════════════════════════════
# TAB 2: 관심 상품
# ══════════════════════════════════════════════════════════════
with tab_monitor:
    tracked_df=load_tracked_db()

    if tracked_df.empty:
        st.markdown("""<div style="text-align:center;padding:3rem 0;color:#94a3b8">
            <div style="font-size:3rem">⭐</div>
            <div style="font-size:1rem;margin-top:.5rem">관심 상품이 없습니다</div>
        </div>""",unsafe_allow_html=True)
    else:
        total_m=len(tracked_df); oos_m=len(tracked_df[tracked_df["status"]!="Y"])
        tracked_df=apply_margin(tracked_df,fee,margin)
        avg_m=int(tracked_df[tracked_df["status"]=="Y"]["예상 순수익(원)"].mean()) if total_m-oos_m>0 else 0

        k1,k2,k3,k4=st.columns(4)
        k1.markdown(f'<div class="kpi-card"><div class="kpi-label">관심 상품</div><div class="kpi-value">{total_m}</div><div class="kpi-sub">개</div></div>',unsafe_allow_html=True)
        k2.markdown(f'<div class="kpi-card"><div class="kpi-label">정상</div><div class="kpi-value" style="color:#16a34a">{total_m-oos_m}</div><div class="kpi-sub">개</div></div>',unsafe_allow_html=True)
        k3.markdown(f'<div class="kpi-card"><div class="kpi-label">품절</div><div class="kpi-value" style="color:#dc2626">{oos_m}</div><div class="kpi-sub">개</div></div>',unsafe_allow_html=True)
        k4.markdown(f'<div class="kpi-card"><div class="kpi-label">평균 순수익</div><div class="kpi-value">{avg_m:,}</div><div class="kpi-sub">원</div></div>',unsafe_allow_html=True)
        st.markdown("<br>",unsafe_allow_html=True)

        mf1,mf2=st.columns([2,1])
        with mf1: m_filter=st.text_input("상품명 검색","",placeholder="관심 상품 내 검색...",label_visibility="collapsed")
        with mf2: m_status=st.selectbox("상태",["전체","정상만","품절만"],label_visibility="collapsed")

        mdf=tracked_df.copy()
        mdf["상태"]=mdf["status"].apply(lambda x:"🟢 정상" if str(x)=="Y" else "❌ 품절")
        for col,default in [("seller_grade",""),("image_url","")]:
            if col not in mdf.columns: mdf[col]=default
        mdf["seller_grade"]=mdf["seller_grade"].fillna("").replace("nan","")

        if m_filter: mdf=mdf[mdf["name"].str.contains(m_filter,case=False,na=False)]
        if m_status=="정상만": mdf=mdf[mdf["status"]=="Y"]
        elif m_status=="품절만": mdf=mdf[mdf["status"]!="Y"]

        mdf["🤖 AI선택"]=False
        mdf["❌ 해제"]=True

        keep=["🤖 AI선택","❌ 해제","site","product_id","name","supply_price","delivery_fee",
              "상태","추천 판매가(원)","예상 순수익(원)","마진율(%)","seller_grade","updated_at"]
        mdf_disp=mdf[[c for c in keep if c in mdf.columns]].copy()
        mdf_disp=mdf_disp.rename(columns={"site":"소싱업체","product_id":"상품번호","name":"상품명",
                                           "supply_price":"공급가(원)","delivery_fee":"배송비(원)",
                                           "seller_grade":"업체등급","updated_at":"등록시간"})

        edited_m=st.data_editor(mdf_disp,use_container_width=True,hide_index=True,key="tracked_editor",
            column_config={
                "🤖 AI선택":st.column_config.CheckboxColumn("🤖 AI선택",width="small",
                    help="체크한 상품만 AI 분석에 포함"),
                "❌ 해제":st.column_config.CheckboxColumn("❌ 해제",default=True,width="small"),
                "소싱업체":st.column_config.TextColumn("소싱업체",width="small"),
                "상품번호":st.column_config.TextColumn("상품번호",width="small"),
                "상품명":st.column_config.TextColumn("상품명",width="large"),
                "공급가(원)":st.column_config.NumberColumn(format="%d원"),
                "배송비(원)":st.column_config.NumberColumn(format="%d원"),
                "추천 판매가(원)":st.column_config.NumberColumn(format="%d원"),
                "예상 순수익(원)":st.column_config.NumberColumn(format="%d원"),
                "마진율(%)":st.column_config.NumberColumn(format="%.1f%%"),
                "업체등급":st.column_config.TextColumn("업체등급",
                    help="⭐S>🔵A>🟢B>🟡C>🟠D>🔴E | B등급 이상 권장"),
                "등록시간":st.column_config.TextColumn("등록시간",
                    help="소싱레이더 DB 저장 시간 (업체 가격 변경 시간 아님)"),
            },
            disabled=[c for c in mdf_disp.columns if c not in ["🤖 AI선택","❌ 해제"]],
        )

        track_changed=False
        for i in range(len(edited_m)):
            if not edited_m.iloc[i]["❌ 해제"]:
                upsert_tracked_product(mdf.iloc[i].to_dict(),0)
                track_changed=True
        if track_changed: st.rerun()

        st.markdown("<br>",unsafe_allow_html=True)

        # 텔레그램 전송
        if st.button("📱 관심 상품 현황을 텔레그램으로 전송",use_container_width=True):
            lines=[f"📊 관심 상품 현황\n전체 {total_m}개 | 정상 {total_m-oos_m}개 | 품절 {oos_m}개\n"]
            for _,row in tracked_df.iterrows():
                icon="🟢" if row["status"]=="Y" else "❌"
                lines.append(f"{icon} {row['name'][:25]} — {int(row['추천 판매가(원)']):,}원 / 수익 {int(row['예상 순수익(원)']):,}원")
            msg="\n".join(lines)
            ok=send_telegram_message(msg)
            if ok: st.success("✅ 전송 완료!")
            else: st.error("❌ 전송 실패")

        # ── AI 소싱 분석 ──────────────────────────────────────
        st.markdown("---")
        st.markdown("#### 🤖 AI 전문 소싱 분석")

        if not GEMINI_KEY:
            st.info("💡 [aistudio.google.com](https://aistudio.google.com)에서 무료 API 키 발급 후 Secrets에 `GEMINI_API_KEY` 등록")
        else:
            selected_rows=edited_m[edited_m["🤖 AI선택"]==True]
            sel_count=len(selected_rows)

            if sel_count==0:
                st.info("💡 위 표에서 **🤖 AI선택** 체크박스를 선택한 뒤 분석을 시작하세요.")
            else:
                st.success(f"✅ {sel_count}개 상품 선택됨")

            col_a1,col_a2=st.columns([2,1])
            with col_a1:
                ai_btn=st.button("✨ 선택 상품 AI 분석",type="primary",
                                  use_container_width=True,disabled=(sel_count==0))
            with col_a2:
                all_btn=st.button("📊 전체 상품 AI 분석",use_container_width=True)

            if all_btn:
                with st.spinner(f"전체 {total_m}개 분석 중... (20~40초)"):
                    result=expert_ai_analyze(tracked_df,fee,margin,platform_name,margin_name)
                st.session_state["ai_result"]=result

            if ai_btn and sel_count>0:
                sel_names=selected_rows["상품명"].tolist()
                sel_df=tracked_df[tracked_df["name"].isin(sel_names)].copy()
                sel_df=apply_margin(sel_df,fee,margin)
                with st.spinner(f"선택한 {sel_count}개 분석 중... (10~30초)"):
                    result=expert_ai_analyze(sel_df,fee,margin,platform_name,margin_name)
                st.session_state["ai_result"]=result

            # ★ 분석 결과 — session_state에서 읽어서 rerun 후에도 유지
            if st.session_state.get("ai_result"):
                st.markdown("---")
                st.markdown("**📊 AI 전문 소싱 분석 결과**")
                result_text=st.session_state["ai_result"]
                st.markdown(result_text)
                st.markdown("<br>",unsafe_allow_html=True)

                # ★ 텔레그램 전송 버튼 — result_text를 변수로 고정해서 rerun 방지
                col_t1,col_t2=st.columns([2,1])
                with col_t1:
                    if st.button("📱 분석 결과를 텔레그램으로 전송",use_container_width=True,key="ai_tg_btn"):
                        # 3000자 제한 (텔레그램 메시지 최대 4096자)
                        tg_msg=f"🤖 AI 소싱 분석 결과\n\n{result_text[:3500]}"
                        ok=send_telegram_message(tg_msg)
                        if ok:
                            st.success("✅ 텔레그램 전송 완료!")
                        else:
                            st.error("❌ 전송 실패. 텔레그램 설정 확인")
                with col_t2:
                    if st.button("🗑 결과 초기화",use_container_width=True,key="ai_clear_btn"):
                        st.session_state["ai_result"]=None
                        st.rerun()

# ══════════════════════════════════════════════════════════════
# TAB 3: 텔레그램 설정
# ══════════════════════════════════════════════════════════════
with tab_telegram:
    st.markdown("### 📱 텔레그램 알림 설정")
    col_a,col_b=st.columns(2)
    with col_a:
        st.markdown("""
#### 봇 만들기
1. 텔레그램 → **@BotFather** 검색
2. `/newbot` 입력 → 이름 설정
3. 발급된 **토큰** 복사

#### 채팅방 ID 확인
```
https://api.telegram.org/bot[토큰]/getUpdates
```
`"chat":{"id":` 뒤 숫자 = 채팅방 ID
        """)
    with col_b:
        st.markdown("#### Secrets 등록")
        st.code("""DOMEGGOOK_API_KEY  = "API키"
TELEGRAM_BOT_TOKEN = "봇토큰"
TELEGRAM_CHAT_ID   = "채팅방ID"
GEMINI_API_KEY     = "제미나이키(무료)"
ONCHANNEL_ID       = "온채널ID(선택)"
ONCHANNEL_PW       = "온채널PW(선택)"
""",language="toml")
        test_msg=st.text_input("테스트 메시지",value="소싱레이더 연동 테스트 ✅")
        if st.button("📤 테스트 발송",type="primary",use_container_width=True):
            ok=send_telegram_message(test_msg)
            st.success("✅ 성공!") if ok else st.error("❌ 실패")

# ══════════════════════════════════════════════════════════════
# TAB 4: 가이드
# ══════════════════════════════════════════════════════════════
with tab_guide:
    st.markdown("### 📖 소싱레이더 사용 가이드")
    with st.expander("🖼 이미지 카드 보기"):
        st.markdown("""
검색 후 우측 보기 방식에서 **🖼 카드** 선택 시 상품 이미지와 함께 카드 형태로 표시됩니다.
- 도매꾹/도매매: 상품 썸네일 자동 로드
- 이미지가 없으면 📦 아이콘으로 표시
        """)
    with st.expander("🤖 AI 분석 사용법"):
        st.markdown("""
1. [aistudio.google.com](https://aistudio.google.com) → **Get API key** → 무료 키 발급
2. Streamlit Secrets에 `GEMINI_API_KEY = "AIza..."` 등록
3. 관심 상품 탭 → **🤖 AI선택** 체크 → **AI 분석 시작**
4. 분석 항목: 마진경쟁력·수익시나리오·업체신뢰도·시장경쟁도·핵심리스크·전략제안·포트폴리오총평
        """)
    with st.expander("🏆 업체 등급 기준"):
        st.markdown("""
| 등급 | 의미 | 소싱 권장 |
|---|---|---|
| ⭐ S등급 | 최우수 | ✅ 강력 권장 |
| 🔵 A등급 | 우수 | ✅ 권장 |
| 🟢 B등급 | 양호 | ✅ 무난 |
| 🟡 C등급 | 보통 | ⚠️ 검토 |
| 🟠 D등급 | 미흡 | ⚠️ 신중 |
| 🔴 E등급 | 불량 | ❌ 비권장 |
> 업체등급은 관심 등록 시 상세 API로 자동 갱신됩니다
        """)
    with st.expander("💡 마진 계산 공식"):
        st.markdown("""
```
추천 판매가 = (공급가 + 배송비) ÷ (1 - 수수료율 - 목표마진율)
예상 순수익 = 판매가 - (판매가 × 수수료율) - 공급가 - 배송비
```
        """)
