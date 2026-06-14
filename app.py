import re as _re
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
.kw-chip{display:inline-block;background:#EFF6FF;color:#1D4ED8;font-size:.78rem;
    padding:3px 10px;border-radius:20px;margin:2px;font-weight:500}
.ai-section{background:white;border-radius:12px;padding:1.2rem 1.4rem;
    border:1px solid #e2e8f0;margin-bottom:1rem}
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
PLATFORM_FEE={
    "네이버 스마트스토어":0.06,"쿠팡":0.11,
    "11번가":0.12,"G마켓":0.12,"옥션":0.12,
}
MARGIN_MAP={"안정형  (10%)":0.10,"밸런스형 (20%)":0.20,"고마진형 (40%)":0.40}
FETCH_PRESETS={"빠른 탐색  (50개)":(50,1),"일반 검색  (100개)":(50,2),
               "심층 분석  (200개)":(50,4),"대량 수집  (500개)":(50,10)}
PLATFORM_KW_GUIDE={
    "네이버 스마트스토어":{"format":"브랜드+상품유형+핵심특징+타겟/용도","max_len":100,"max_kw":10,
        "tip":"정확한 상품명+핵심 키워드 조합 선호. 브랜드명+상품유형+특징 순서 유지"},
    "쿠팡":{"format":"핵심상품명+용량/수량+주요특징","max_len":50,"max_kw":8,
        "tip":"상품명 간결하게, 태그에 롱테일 키워드 분산"},
    "11번가":{"format":"브랜드+상품명+모델명/규격+수량","max_len":80,"max_kw":10,
        "tip":"가격 경쟁력과 상세한 상품명 효과적"},
    "G마켓":{"format":"브랜드+상품유형+특징+구성/용량","max_len":80,"max_kw":10,
        "tip":"카테고리 최적화 중요"},
    "옥션":{"format":"브랜드+상품유형+구성수량+할인/혜택","max_len":80,"max_kw":10,
        "tip":"기획전/딜 노출 중요. 가격 경쟁력 강조"},
}

# v9.0 PDF 가이드 — 정밀 규격
IMAGE_SPEC = [
    {"no":1, "stage":"HOOK",         "kr":"훅",       "w":860,"h":2200},
    {"no":2, "stage":"Painpoint",    "kr":"문제 공감", "w":860,"h":1800},
    {"no":3, "stage":"Solution",     "kr":"해결 제안", "w":860,"h":2000},
    {"no":4, "stage":"USP1",         "kr":"핵심 가치1","w":860,"h":1800},
    {"no":5, "stage":"USP2",         "kr":"핵심 가치2","w":860,"h":1800},
    {"no":6, "stage":"USP3",         "kr":"핵심 가치3","w":860,"h":1800},
    {"no":7, "stage":"USP4",         "kr":"핵심 가치4","w":860,"h":1800},
    {"no":8, "stage":"TPO",          "kr":"활용성",    "w":860,"h":1800},
    {"no":9, "stage":"Certification","kr":"신뢰",      "w":860,"h":2500},
    {"no":10,"stage":"SpecsInfo",    "kr":"상세 정보", "w":860,"h":2800},
    {"no":11,"stage":"Audience",     "kr":"추천 대상", "w":860,"h":1600},
    {"no":12,"stage":"CTA",          "kr":"행동 유도", "w":860,"h":1800},
]

for k,v in {
    "live_results":[],"show_results":False,"search_error":None,
    "page_num":0,"ai_result":None,
    "live_view":"card","mon_view":"card",
    "kw_result":None,"img_prompt":None,
    "card_ai_selected":set(),
    "tg_sidebar_msg":""
}.items():
    if k not in st.session_state:
        st.session_state[k]=v

# ── 헬퍼 ─────────────────────────────────────────────────────
def fmt_dt(dt_str):
    if not dt_str or str(dt_str) in ("nan","None",""): return ""
    try:
        dt=datetime.strptime(str(dt_str)[:19],"%Y-%m-%d %H:%M:%S")
        return dt.strftime("%y.%m.%d")
    except: return str(dt_str)[:10]

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

def apply_margin(df,fee,margin):
    df=df.copy()
    df["추천 판매가(원)"]=df.apply(lambda r:calculate_target_price(r["supply_price"],r["delivery_fee"],fee,margin),axis=1)
    df["예상 순수익(원)"]=df.apply(lambda r:calculate_expected_profit(r["추천 판매가(원)"],r["supply_price"],r["delivery_fee"],fee),axis=1)
    df["마진율(%)"]=df.apply(lambda r:round(r["예상 순수익(원)"]/r["추천 판매가(원)"]*100,1) if r["추천 판매가(원)"]>0 else 0,axis=1)
    return df

def do_live_search():
    st.session_state.update({"search_error":None,"page_num":0,"live_results":[],
                              "ai_result":None,"show_results":False,"card_ai_selected":set()})
    kw   = st.session_state.get("search_kw","").strip()
    cat  = CATEGORY_MAP[st.session_state["cat_main"]][st.session_state["cat_sub"]]
    sites= st.session_state.get("sourcing_sites",["도매매","도매꾹"])
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

    # ★ 분석 보고서 보완: 온채널 실패해도 전체 검색 마비 안 됨
    if "온채널" in sites and oc_client:
        if not OC_ID or not OC_PW:
            errors.append("온채널 ID/PW 미설정")
        elif kw:
            oc_items = oc_client.fetch_product_list(keyword=kw,page_size=pg_size*max_pg,max_pages=max_pg)
            if oc_items:
                results.extend(oc_items)
            elif oc_client.last_error:
                errors.append(f"온채널: {oc_client.last_error}")

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
                              "search_error":None,"page_num":0,"ai_result":None,"card_ai_selected":set()})
    st.rerun()

def do_track(prod, is_track):
    if is_track and client and prod.get("site") in ["도매매","도매꾹"]:
        detail=client.fetch_item_detail(str(prod["product_id"]))
        if detail:
            for k,v in detail.items():
                if v or v==0: prod[k]=v
    upsert_tracked_product(prod, is_track)

def get_product_url(row):
    site=row.get("site",""); pid=str(row.get("product_id",""))
    if site in ["도매꾹","도매매"]:
        mkt = "" if site=="도매꾹" else "&market=supply"
        return f"https://domeggook.com/main/item/itemView.php?no={pid}{mkt}"
    elif pid.startswith("OC_"):
        return f"https://www.onch3.co.kr/goods_view.php?vnum={pid[3:]}"
    return ""

def render_cards(df, tracked_ids, id_prefix, on_toggle,
                 show_ai_select=False, ai_selected_set=None):
    per_row=3
    for i in range(0,len(df),per_row):
        cols=st.columns(per_row)
        for ci,(_,row) in enumerate(df.iloc[i:i+per_row].iterrows()):
            with cols[ci]:
                grade=str(row.get("seller_grade","")).strip()
                img=str(row.get("image_url","")).strip()
                profit=int(row.get("예상 순수익(원)",0))
                sale=int(row.get("추천 판매가(원)",0))
                mp=float(row.get("마진율(%)",0))
                pid=str(row["product_id"])
                is_t=pid in tracked_ids
                prod_url=get_product_url(row)

                if img and img.startswith("http"):
                    if prod_url:
                        st.markdown(f'<a href="{prod_url}" target="_blank"><img src="{img}" '
                                    f'style="width:100%;border-radius:8px;cursor:pointer;'
                                    f'margin-bottom:6px"/></a>', unsafe_allow_html=True)
                    else:
                        try: st.image(img,width=220)
                        except: st.markdown("📦")
                else:
                    link_open=f'href="{prod_url}" target="_blank"' if prod_url else ""
                    st.markdown(f'<a {link_open} style="text-decoration:none"><div style="height:90px;'
                                f'background:#f1f5f9;border-radius:8px;display:flex;align-items:center;'
                                f'justify-content:center;font-size:2.5rem;margin-bottom:6px;'
                                f'cursor:pointer">📦</div></a>', unsafe_allow_html=True)

                gc={"S":"#f59e0b","A":"#3b82f6","B":"#22c55e","C":"#eab308",
                    "D":"#f97316","E":"#ef4444"}.get(
                    grade[0].upper() if grade and grade[0].isalpha() else "","#94a3b8")
                name_link=(f'<a href="{prod_url}" target="_blank" style="color:#1e293b;text-decoration:none">'
                           f'{row["name"][:30]}</a>' if prod_url else row["name"][:30])
                st.markdown(f"""
<div style="font-size:.82rem;font-weight:500;white-space:nowrap;overflow:hidden;
    text-overflow:ellipsis;margin-bottom:3px" title="{row['name']}">{name_link}</div>
<div style="font-size:.7rem;color:#94a3b8;margin-bottom:3px">{row.get('site','')} | {pid}</div>
<div style="font-size:.75rem;color:#475569;margin-bottom:2px">
    공급가 <b>{int(row['supply_price']):,}원</b> 배송비 <b>{int(row['delivery_fee']):,}원</b></div>
<div style="font-size:.9rem;font-weight:700;color:#2563eb;margin-bottom:2px">
    판매가 {sale:,}원 &nbsp; 순수익 {profit:,}원</div>
<div style="font-size:.72rem;color:#64748b">
    마진 <b>{mp:.1f}%</b> &nbsp;|&nbsp;
    등급 <span style="color:{gc};font-weight:600">{grade if grade else '조회 필요'}</span>
    &nbsp;|&nbsp; {row.get('상태','')}</div>""", unsafe_allow_html=True)

                if show_ai_select and ai_selected_set is not None:
                    ai_checked=pid in ai_selected_set
                    new_checked=st.checkbox("🤖 AI분석 선택",value=ai_checked,
                                            key=f"ai_chk_{id_prefix}_{pid}")
                    if new_checked!=ai_checked:
                        if new_checked: ai_selected_set.add(pid)
                        else: ai_selected_set.discard(pid)
                        st.session_state["card_ai_selected"]=ai_selected_set

                label="⭐ 등록됨" if is_t else "☆ 관심 등록"
                if st.button(label,key=f"{id_prefix}_card_{pid}",use_container_width=True):
                    on_toggle(row.to_dict(),0 if is_t else 1); st.rerun()

def send_tg_long(text, prefix="📡 소싱레이더"):
    import time as _t
    chunks=[text[i:i+3800] for i in range(0,len(text),3800)]
    total=len(chunks); ok=True
    for i,chunk in enumerate(chunks):
        hdr=prefix if total==1 else f"{prefix} ({i+1}/{total})"
        if not send_telegram_message(f"{hdr}\n\n{chunk}"): ok=False
        if i<len(chunks)-1: _t.sleep(0.5)
    return ok

def gemini_call(prompt, max_tokens=2000):
    if not GEMINI_KEY: return "GEMINI_API_KEY 미설정"
    try:
        resp=req.post(
            f"https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash-lite:generateContent?key={GEMINI_KEY}",
            headers={"Content-Type":"application/json"},
            json={"contents":[{"parts":[{"text":prompt}]}],
                  "generationConfig":{"maxOutputTokens":max_tokens,"temperature":0.1}},
            timeout=90,
        )
        if resp.status_code==200:
            return resp.json()["candidates"][0]["content"]["parts"][0]["text"]
        return f"Gemini 오류 {resp.status_code}: {resp.text[:200]}"
    except Exception as e:
        return f"AI 연결 오류: {e}"

def compact_ai(items_df,fee,margin,platform_name,margin_name):
    rows=[]
    for _,r in items_df.iterrows():
        profit=int(r.get("예상 순수익(원)",0)); sale=int(r.get("추천 판매가(원)",0))
        supply=int(r.get("supply_price",0)); deliv=int(r.get("delivery_fee",0))
        mp=float(r.get("마진율(%)",0)); grade=r.get("seller_grade","미확인") or "미확인"
        rows.append(f"{r['name'][:28]} ({r.get('site','')})\n"
                    f"  원가{supply+deliv:,}원 판매가{sale:,}원 순수익{profit:,}원/건 마진{mp:.1f}% 등급{grade}")
    prompt=f"""이커머스 소싱 전문가로서 마케팅과 판매 관점에서 핵심만 분석하세요.
판매 설정: {platform_name} 수수료{int(fee*100)}% / 목표마진 {int(margin*100)}%
분석 상품:
{chr(10).join(rows)}

아래 형식으로만 출력하세요. 줄 앞에 대시(-), 해시(#), 별표(*) 없이. 이모티콘 유지.

🏆 즉시 소싱 추천 TOP3
1 상품명 이유한줄
2 상품명 이유한줄
3 상품명 이유한줄

❌ 제외 권장
상품명 이유한줄

📊 개별 판정
상품명 판정(✅강력추천/👍추천/⚠️주의/❌비추천) 마진경쟁력(상중하) 리스크한줄 월50건수익 원

💡 이번달 전략
1 핵심액션
2 핵심액션
3 핵심액션

⚠️ 주의사항
내용 2줄 이내"""
    return gemini_call(prompt,1800)

def generate_keywords(prod_name, features, platforms):
    guide_str="\n".join([f"[{p}] 형식={PLATFORM_KW_GUIDE[p]['format']}, 최대{PLATFORM_KW_GUIDE[p]['max_len']}자" for p in platforms])
    prompt=f"""이커머스 SEO 전문가. 아래 상품의 플랫폼별 최적 키워드를 생성하세요.
상품명: {prod_name}
주요 특징: {features}
{guide_str}

각 플랫폼별 출력 (## 없이, 이모티콘 유지):
[플랫폼명]
추천 상품명: (최적 상품명)
핵심 키워드: 키워드1, 키워드2, 키워드3, 키워드4, 키워드5
롱테일 키워드: 키워드1, 키워드2, 키워드3
태그: 태그1, 태그2, 태그3, 태그4, 태그5
등록 팁: 한줄

플랫폼 간 구분: ---"""
    return gemini_call(prompt,2000)

def fetch_url_content(url: str) -> str:
    if not url or not url.startswith("http"): return ""
    try:
        from bs4 import BeautifulSoup
        resp=req.get(url,headers={"User-Agent":"Mozilla/5.0"},timeout=10)
        if resp.status_code==200:
            resp.encoding=resp.apparent_encoding
            soup=BeautifulSoup(resp.text,"html.parser")
            for tag in soup(["script","style","nav","footer","header"]): tag.decompose()
            return soup.get_text(separator="\n",strip=True)[:2000]
    except Exception as e: print(f"[URL fetch] {e}")
    return ""

def generate_image_prompts_v9(brand, product_url, features, target, category):
    """
    소싱레이더 AI 마스터 가이드북 v9.0 기준
    - DALL-E 3 전용 영문 프롬프트
    - 상단 40% 솔리드 배경 강제
    - 12단계 정밀 규격 (정확한 px 높이)
    - 가짜 데이터 생성 금지
    """
    url_content=""
    if product_url and product_url.startswith("http"):
        url_content=fetch_url_content(product_url)
        if url_content:
            url_content=f"\n\n[참고 URL 내용]\n{url_content}"

    specs="\n".join([f"이미지{s['no']:02d} {s['stage']}({s['kr']}): {s['w']}×{s['h']}px" for s in IMAGE_SPEC])

    prompt=f"""You are a senior e-commerce visual designer and performance marketer specializing in Korean Smartstore detail pages.
Follow the SourcingRadar AI Master Blueprint v9.0 specifications strictly.

Product Information:
Brand: {brand}
Category: {category}
Target Audience: {target}
Key Features:
{features}{url_content}

CRITICAL RULES (v9.0):
1. Generate exactly 12 independent image prompts — 1 section = 1 PNG file
2. Every prompt MUST include: "The top 40% of the vertical canvas must be entirely filled with a flat, solid, single-tone background color containing no textures, objects, or patterns. Reserve this space strictly for clear copywriting overlay."
3. Use DALL-E 3 optimized English prompts only
4. Never fabricate review ratings, sales numbers, or certifications unless provided
5. Never merge multiple sections into one image (no collage)
6. Maintain exact pixel dimensions per spec

Image Specs:
{specs}

For each image, output in this EXACT format:

[Image N: STAGE_NAME]
한국어 제목: (Korean section title)
목적: (Purpose in Korean)
이미지 규격: {IMAGE_SPEC[0]['w']}×HEIGHT px
메인 카피: (Korean headline, 15-25 characters)
서브 카피: (Korean sub-headline, 1-2 sentences)
보조 포인트: Point1 / Point2 / Point3
DALL-E 3 Prompt:
Photorealistic, commercial photography, [specific scene description], [product placement], The top 40% of the vertical canvas must be entirely filled with a flat, solid, [COLOR] single-tone background color containing no textures, objects, or patterns. Reserve this space strictly for clear copywriting overlay. Clean ecommerce design, natural lighting, realistic texture, high detail, {IMAGE_SPEC[0]['w']}px width, [HEIGHT]px height, no text overlay, no watermark.

Generate all 12 images following the sequence: HOOK → Painpoint → Solution → USP1 → USP2 → USP3 → USP4 → TPO → Certification → SpecsInfo → Audience → CTA"""

    return gemini_call(prompt, 4000)

def build_download_text(brand, prompt_text):
    return f"""소싱레이더 AI 상세페이지 마스터 가이드북 v9.0
브랜드: {brand}
생성일: {datetime.now().strftime('%Y.%m.%d %H:%M')}
규격: 860px 고정 / 12개 이미지 / DALL-E 3 최적화
{'='*60}

사용 방법:
1. 각 [Image N]의 'DALL-E 3 Prompt:' 부분을 복사
2. ChatGPT (GPT-4o with image generation)에 붙여넣기
3. "이 프롬프트로 이미지를 생성해줘" 라고 함께 입력
4. 생성된 이미지를 860px 기준으로 저장
5. 스마트스토어 상세페이지에 01~12 순서로 등록

파일명 규칙: {brand}_01_HOOK.png ... {brand}_12_CTA.png
ZIP 번들명: {brand}_상세페이지.zip

{'='*60}

{prompt_text}
"""

# ── 사이드바 ─────────────────────────────────────────────────
with st.sidebar:
    st.markdown("## 📡 소싱레이더")
    st.markdown("---")
    st.markdown("#### 소싱 설정")
    site_opts=["도매매","도매꾹"]
    if OC_AVAILABLE: site_opts.append("온채널")
    sourcing_sites=st.multiselect("소싱 업체",options=site_opts,default=["도매매","도매꾹"],key="sourcing_sites")
    if OC_AVAILABLE:
        if OC_ID and OC_PW:
            st.caption("온채널: 로그인 정보 등록됨 (클라우드 차단으로 검색 불가)")
        else:
            st.caption("온채널: ID/PW 미설정")
    fetch_preset=st.selectbox("검색 수량",list(FETCH_PRESETS.keys()),index=1,key="fetch_preset")
    st.markdown("#### 판매 전략")
    platform_name=st.selectbox("판매 플랫폼",list(PLATFORM_FEE.keys()))
    margin_name=st.select_slider("마진 전략",options=list(MARGIN_MAP.keys()))
    fee=PLATFORM_FEE[platform_name]; margin=MARGIN_MAP[margin_name]
    st.markdown(f"""<div style="background:#0f3460;border-radius:10px;padding:.8rem 1rem;margin-top:.5rem">
        <div style="color:#94a3b8;font-size:.72rem;font-weight:600">현재 설정</div>
        <div style="color:white;font-size:1rem;font-weight:700;margin-top:.2rem">수수료 {int(fee*100)}% / 목표마진 {int(margin*100)}%</div>
        <div style="color:#64748b;font-size:.72rem;margin-top:.2rem">배수 ÷{round(1-fee-margin,2)}</div>
    </div>""",unsafe_allow_html=True)
    st.markdown("---")
    t_df=load_tracked_db()
    total_t=len(t_df)
    avg_p_t=int(apply_margin(t_df,fee,margin)["예상 순수익(원)"].mean()) if not t_df.empty else 0
    st.markdown("#### 관심 상품")
    c1,c2=st.columns(2); c1.metric("등록",total_t); c2.metric("평균수익",f"{avg_p_t:,}원")
    st.markdown("---")
    st.markdown("#### 텔레그램")
    try: tg_ok=st.secrets.get("TELEGRAM_BOT_TOKEN","") not in ["","봇토큰_입력"]
    except: tg_ok=False
    st.markdown(f"상태: {'연동됨' if tg_ok else '미설정'}")

    # ★ 사이드바 버튼 — DeltaGenerator 오류 수정
    # st.success/error를 sidebar 컨텍스트 안에 고정 배치
    sb_tg_result = st.empty()
    if st.button("테스트 발송",use_container_width=True,key="sb_tg_btn"):
        ok=send_telegram_message(f"소싱레이더 연동 테스트\n관심상품 {total_t}개")
        if ok:
            sb_tg_result.success("✅ 발송 완료")
        else:
            sb_tg_result.error("❌ 발송 실패")

    st.markdown("---")
    st.markdown(f"#### AI (Gemini 무료)\n{'사용 가능' if GEMINI_KEY else 'GEMINI_API_KEY 미설정'}")
    st.markdown("---")
    st.caption("소싱레이더 v7.0 | PDF 가이드 v9.0 적용")

# ── 헤더 ────────────────────────────────────────────────────
st.markdown("""<div class="main-header">
    <h1>📡 소싱레이더</h1>
    <p>도매매 도매꾹 실시간 통합 마진 분석 시스템 | AI 상세페이지 v9.0</p>
</div>""",unsafe_allow_html=True)

tab1,tab2,tab3,tab4,tab5,tab6=st.tabs([
    "🔍 라이브 검색","⭐ 관심 상품","🔑 키워드 생성","🎨 AI 이미지 생성","📱 텔레그램","📖 가이드"])

# ══════════════════════════════════════════════════════════════
# TAB 1: 라이브 검색
# ══════════════════════════════════════════════════════════════
with tab1:
    r1,r2,r3=st.columns([1.2,1.2,2.6])
    with r1: main_cat=st.selectbox("대분류",list(CATEGORY_MAP.keys()),key="cat_main")
    with r2: st.selectbox("중분류",list(CATEGORY_MAP[main_cat].keys()),key="cat_sub")
    with r3: st.text_input("키워드",key="search_kw",placeholder="예: 백팩, 무선이어폰...",on_change=do_live_search)
    b1,b2,b3,_=st.columns([1.5,1,1.2,2])
    with b1: st.button("검색",on_click=do_live_search,use_container_width=True,type="primary")
    with b2: st.button("초기화",on_click=reset_all,use_container_width=True)
    with b3:
        v_sel=st.selectbox("보기",["🖼 카드 보기","📋 표 보기"],key="live_view_sel",label_visibility="collapsed")
        st.session_state["live_view"]="card" if "카드" in v_sel else "table"

    if st.session_state.get("search_error"):
        st.warning(st.session_state["search_error"])

    if not st.session_state["show_results"]:
        st.markdown("""<div style="text-align:center;padding:3rem 0;color:#94a3b8">
            <div style="font-size:3rem">📦</div>
            <div style="font-size:1rem;margin-top:.5rem">키워드를 입력하고 검색하세요</div>
        </div>""",unsafe_allow_html=True)
    else:
        raw_df=pd.DataFrame(st.session_state["live_results"])
        if raw_df.empty:
            st.info("검색 결과가 없습니다.")
        else:
            for col,default in [("seller_grade",""),("image_url","")]:
                if col not in raw_df.columns: raw_df[col]=default

            grade_missing=int((raw_df["seller_grade"]=="").sum()+(raw_df["seller_grade"].isna()).sum())
            if grade_missing>0 and client:
                col_gb,_=st.columns([2.5,3])
                with col_gb:
                    if st.button(f"🏅 업체등급 조회 (상위15개, 약5~10초)",
                                 use_container_width=True,type="secondary"):
                        with st.spinner("업체등급 상세 조회 중..."):
                            updated=client.batch_fetch_grades(raw_df.to_dict("records"),limit=15)
                            st.session_state["live_results"]=pd.DataFrame(updated).to_dict("records")
                        st.rerun()

            site_counts=raw_df["site"].value_counts().to_dict()
            badge=" | ".join(f"{s} {n}개" for s,n in site_counts.items())
            st.markdown(f"<div style='color:#64748b;font-size:.85rem;margin-bottom:.5rem'>검색결과: {badge} / 총 {len(raw_df):,}개</div>",unsafe_allow_html=True)

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
            k3.markdown(f'<div class="kpi-card"><div class="kpi-label">평균 순수익</div><div class="kpi-value">{avg_p:,}</div><div class="kpi-sub">원/건</div></div>',unsafe_allow_html=True)
            k4.markdown(f'<div class="kpi-card"><div class="kpi-label">최고 순수익</div><div class="kpi-value" style="color:#2563eb">{max_p:,}</div><div class="kpi-sub">원/건</div></div>',unsafe_allow_html=True)
            st.markdown("<br>",unsafe_allow_html=True)

            disp_size=50 if st.session_state["live_view"]=="table" else 18
            total_pg=max(1,(len(df)+disp_size-1)//disp_size)
            page_num=min(st.session_state["page_num"],total_pg-1)
            page_df=df.iloc[page_num*disp_size:(page_num+1)*disp_size].copy()
            tracked_ids=load_tracked_db()["product_id"].astype(str).tolist()
            page_df["⭐ 관심"]=page_df["product_id"].astype(str).isin(tracked_ids)

            if st.session_state["live_view"]=="card":
                render_cards(page_df,tracked_ids,"live1",lambda p,t:do_track(p,t))
            else:
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
                        "업체등급":st.column_config.TextColumn("업체등급"),
                    })
                any_changed=False
                for i in range(len(edited)):
                    if edited.iloc[i]["⭐ 관심"]!=disp.iloc[i]["⭐ 관심"]:
                        prod=page_df.iloc[i].to_dict()
                        is_t=1 if edited.iloc[i]["⭐ 관심"] else 0
                        do_track(prod,is_t); any_changed=True
                if any_changed: st.rerun()

            pn1,pn2,pn3=st.columns([1,3,1])
            with pn1:
                if st.button("이전",disabled=(page_num==0),use_container_width=True):
                    st.session_state["page_num"]=page_num-1; st.rerun()
            with pn2:
                st.markdown(f"<div style='text-align:center;color:#64748b;font-size:.85rem;padding-top:.5rem'>{page_num+1}/{total_pg} | 총 {len(df):,}개</div>",unsafe_allow_html=True)
            with pn3:
                if st.button("다음",disabled=(page_num>=total_pg-1),use_container_width=True):
                    st.session_state["page_num"]=page_num+1; st.rerun()

# ══════════════════════════════════════════════════════════════
# TAB 2: 관심 상품
# ══════════════════════════════════════════════════════════════
with tab2:
    tracked_df=load_tracked_db()
    if tracked_df.empty:
        st.markdown("""<div style="text-align:center;padding:3rem 0;color:#94a3b8">
            <div style="font-size:3rem">⭐</div>
            <div style="font-size:1rem;margin-top:.5rem">관심 상품이 없습니다</div>
        </div>""",unsafe_allow_html=True)
    else:
        total_m=len(tracked_df); t_calc=apply_margin(tracked_df,fee,margin)
        ok_m=len(tracked_df[tracked_df["status"]=="Y"])
        avg_m=round(t_calc["마진율(%)"].mean(),1)
        avg_prof=int(t_calc[t_calc["status"]=="Y"]["예상 순수익(원)"].mean()) if ok_m>0 else 0
        monthly=avg_prof*100

        k1,k2,k3,k4=st.columns(4)
        k1.markdown(f'<div class="kpi-card"><div class="kpi-label">관심 상품</div><div class="kpi-value">{total_m}</div><div class="kpi-sub">개</div></div>',unsafe_allow_html=True)
        k2.markdown(f'<div class="kpi-card"><div class="kpi-label">정상 판매</div><div class="kpi-value" style="color:#16a34a">{ok_m}</div><div class="kpi-sub">개</div></div>',unsafe_allow_html=True)
        k3.markdown(f'<div class="kpi-card"><div class="kpi-label">평균 마진율</div><div class="kpi-value" style="color:#7c3aed">{avg_m:.1f}%</div><div class="kpi-sub">목표마진 기준</div></div>',unsafe_allow_html=True)
        k4.markdown(f'<div class="kpi-card"><div class="kpi-label">월 예상수익 (100건)</div><div class="kpi-value" style="color:#2563eb">{monthly:,}</div><div class="kpi-sub">원</div></div>',unsafe_allow_html=True)
        st.markdown("<br>",unsafe_allow_html=True)

        mv1,mv2,mv3=st.columns([2,1,1])
        with mv1: m_filter=st.text_input("상품명 검색","",placeholder="검색...",label_visibility="collapsed")
        with mv2: m_status=st.selectbox("상태",["전체","정상만","품절만"],label_visibility="collapsed")
        with mv3:
            mv_sel=st.selectbox("보기",["🖼 카드 보기","📋 표 보기"],key="mon_view_sel",label_visibility="collapsed")
            st.session_state["mon_view"]="card" if "카드" in mv_sel else "table"

        mdf=t_calc.copy()
        mdf["상태"]=mdf["status"].apply(lambda x:"🟢 정상" if str(x)=="Y" else "❌ 품절")
        for col,default in [("seller_grade",""),("image_url","")]:
            if col not in mdf.columns: mdf[col]=default
        mdf["seller_grade"]=mdf["seller_grade"].fillna("").replace("nan","")
        if m_filter: mdf=mdf[mdf["name"].str.contains(m_filter,case=False,na=False)]
        if m_status=="정상만": mdf=mdf[mdf["status"]=="Y"]
        elif m_status=="품절만": mdf=mdf[mdf["status"]!="Y"]

        tracked_ids_m=mdf["product_id"].astype(str).tolist()
        edited_m=None
        card_ai=st.session_state.get("card_ai_selected",set())

        if st.session_state["mon_view"]=="card":
            render_cards(mdf,tracked_ids_m,"mon",
                         lambda p,t:(upsert_tracked_product(p,t),st.rerun()),
                         show_ai_select=True,ai_selected_set=card_ai)
        else:
            # ★ 분석 보고서 보완: product_id 기준 인덱스 매핑 — 필터링 시 잘못된 행 해제 방지
            mdf_reset = mdf.reset_index(drop=True)
            mdf_reset["AI선택"]=False; mdf_reset["해제"]=True
            if "updated_at" in mdf_reset.columns:
                mdf_reset["등록일"]=mdf_reset["updated_at"].apply(fmt_dt)
            keep=["AI선택","해제","site","product_id","name","supply_price","delivery_fee",
                  "상태","추천 판매가(원)","예상 순수익(원)","마진율(%)","seller_grade","등록일"]
            mdf_disp=mdf_reset[[c for c in keep if c in mdf_reset.columns]].copy()
            mdf_disp=mdf_disp.rename(columns={"site":"소싱업체","product_id":"상품번호","name":"상품명",
                                               "supply_price":"공급가(원)","delivery_fee":"배송비(원)",
                                               "seller_grade":"업체등급"})
            edited_m=st.data_editor(mdf_disp,use_container_width=True,hide_index=True,key="tracked_editor",
                column_config={
                    "AI선택":st.column_config.CheckboxColumn("AI선택",width="small",help="AI 분석 포함"),
                    "해제":st.column_config.CheckboxColumn("해제",default=True,width="small"),
                    "소싱업체":st.column_config.TextColumn("소싱업체",width="small"),
                    "상품번호":st.column_config.TextColumn("상품번호",width="small"),
                    "상품명":st.column_config.TextColumn("상품명",width="large"),
                    "공급가(원)":st.column_config.NumberColumn(format="%d원"),
                    "배송비(원)":st.column_config.NumberColumn(format="%d원"),
                    "추천 판매가(원)":st.column_config.NumberColumn(format="%d원"),
                    "예상 순수익(원)":st.column_config.NumberColumn(format="%d원"),
                    "마진율(%)":st.column_config.NumberColumn(format="%.1f%%"),
                    "업체등급":st.column_config.TextColumn("업체등급"),
                    "등록일":st.column_config.TextColumn("등록일"),
                },
                disabled=[c for c in mdf_disp.columns if c not in ["AI선택","해제"]],
            )
            # ★ 인덱스 매핑 수정: 상품번호(product_id)로 매칭
            track_changed=False
            for i in range(len(edited_m)):
                if not edited_m.iloc[i]["해제"]:
                    pid_to_remove=edited_m.iloc[i]["상품번호"]
                    # product_id로 원본 찾기 — 필터링과 무관하게 정확히 매핑
                    match=mdf_reset[mdf_reset["product_id"]==pid_to_remove]
                    if not match.empty:
                        upsert_tracked_product(match.iloc[0].to_dict(),0)
                        track_changed=True
            if track_changed: st.rerun()

        st.markdown("<br>",unsafe_allow_html=True)

        # 텔레그램 전송 — ★ 탭 컨텍스트 안에 placeholder 고정
        tg2_ph=st.empty()
        if st.button("📱 관심 상품 현황 텔레그램 전송",use_container_width=True):
            lines=[f"관심 상품 현황\n전체 {total_m}개 / 정상 {ok_m}개 / 평균마진 {avg_m:.1f}%\n"]
            for _,row in t_calc.iterrows():
                icon="O" if row["status"]=="Y" else "X"
                lines.append(f"{icon} {row['name'][:22]} 판매가{int(row['추천 판매가(원)']):,}원 수익{int(row['예상 순수익(원)']):,}원")
            ok_sent=send_tg_long("\n".join(lines),"관심 상품 현황")
            if ok_sent: tg2_ph.success("✅ 전송 완료")
            else: tg2_ph.error("❌ 전송 실패")

        st.markdown("---")
        st.markdown("#### 🤖 AI 소싱 분석")
        if not GEMINI_KEY:
            st.info("aistudio.google.com 에서 무료 키 발급 후 Secrets에 GEMINI_API_KEY 등록")
        else:
            sel_count=0; sel_df=pd.DataFrame()
            if st.session_state["mon_view"]=="card":
                sel_pids=st.session_state.get("card_ai_selected",set())
                sel_count=len(sel_pids)
                if sel_count>0:
                    sel_df=t_calc[t_calc["product_id"].astype(str).isin(sel_pids)].copy()
                if sel_count>0: st.success(f"{sel_count}개 선택됨")
                else: st.info("카드에서 🤖 AI분석 선택 체크 후 분석하거나 전체 분석 버튼 사용")
            elif edited_m is not None and "AI선택" in edited_m.columns:
                sel_rows=edited_m[edited_m["AI선택"]==True]; sel_count=len(sel_rows)
                if sel_count>0:
                    sel_pids_t=sel_rows["상품번호"].tolist()
                    sel_df=t_calc[t_calc["product_id"].isin(sel_pids_t)].copy()
                if sel_count>0: st.success(f"{sel_count}개 선택됨")
                else: st.info("표에서 AI선택 체크 후 분석하거나 전체 분석 버튼 사용")

            btn1,btn2=st.columns([2,1])
            with btn1: ai_sel_btn=st.button("✨ 선택 상품 AI 분석",type="primary",use_container_width=True,disabled=(sel_count==0))
            with btn2: ai_all_btn=st.button("📊 전체 AI 분석",use_container_width=True)

            ai_result_ph=st.empty()
            if ai_all_btn:
                with st.spinner(f"전체 {total_m}개 분석 중..."): result=compact_ai(t_calc,fee,margin,platform_name,margin_name)
                st.session_state["ai_result"]=result
            if ai_sel_btn and sel_count>0:
                target=apply_margin(sel_df,fee,margin)
                with st.spinner(f"{sel_count}개 분석 중..."): result=compact_ai(target,fee,margin,platform_name,margin_name)
                st.session_state["ai_result"]=result

            if st.session_state.get("ai_result"):
                st.markdown("---")
                st.markdown("**📊 AI 소싱 분석 결과**")
                result_text=st.session_state["ai_result"]
                st.markdown(result_text)
                ai_tg_ph=st.empty()
                tg_col,clr_col=st.columns([2,1])
                with tg_col:
                    if st.button("📱 분석 결과 텔레그램 전송",use_container_width=True,key="ai_tg"):
                        ok_sent=send_tg_long(result_text,"🤖 AI 소싱 분석")
                        if ok_sent: ai_tg_ph.success("✅ 전송 완료")
                        else: ai_tg_ph.error("❌ 전송 실패")
                with clr_col:
                    if st.button("결과 초기화",use_container_width=True,key="ai_clr"):
                        st.session_state["ai_result"]=None; st.rerun()

# ══════════════════════════════════════════════════════════════
# TAB 3: 키워드 생성
# ══════════════════════════════════════════════════════════════
with tab3:
    st.markdown("### 🔑 플랫폼별 키워드 생성")
    st.markdown('<div class="ai-section">',unsafe_allow_html=True)
    kw_prod=st.text_input("상품명",placeholder="예: 오트밀크 190ml 24팩",key="kw_product_input")
    kw_feat=st.text_area("주요 특징",placeholder="예: 비건, 무첨가, 오트밀 함량 11%",height=80,key="kw_features_input")
    kw_platforms=st.multiselect("등록할 플랫폼",options=list(PLATFORM_KW_GUIDE.keys()),
                                default=["네이버 스마트스토어","쿠팡"],key="kw_platforms")
    if st.session_state.get("live_results"):
        live_names=["직접 입력"]+[r["name"] for r in st.session_state["live_results"][:20]]
        sel_from_live=st.selectbox("또는 검색 결과에서 선택",live_names,key="kw_from_live")
        if sel_from_live!="직접 입력":
            st.caption(f"선택됨: {sel_from_live}")
    if st.button("🔑 키워드 생성",type="primary",use_container_width=True,
                 disabled=(not GEMINI_KEY or not kw_prod or not kw_platforms)):
        with st.spinner("플랫폼별 키워드 생성 중..."):
            actual_name=(sel_from_live if (st.session_state.get("live_results") and
                         st.session_state.get("kw_from_live","직접 입력")!="직접 입력") else kw_prod)
            result=generate_keywords(actual_name,kw_feat,kw_platforms)
        st.session_state["kw_result"]=result
    st.markdown('</div>',unsafe_allow_html=True)

    if st.session_state.get("kw_result"):
        st.markdown("---")
        st.markdown("**🔑 플랫폼별 키워드 결과**")
        result_text=st.session_state["kw_result"]

        # 결과 내 재검색
        kw_inner=st.text_input("결과 내 재검색","",
                               placeholder="키워드 입력 시 해당 플랫폼만 표시...",
                               key="kw_inner_filter")

        sections=[s.strip() for s in result_text.split("---") if s.strip()]
        for section in sections:
            lines=[l.strip() for l in section.split("\n") if l.strip()]
            if not lines: continue
            header=lines[0].replace("##","").strip().strip("[]").strip()
            if kw_inner and kw_inner.lower() not in section.lower(): continue

            with st.expander(f"📍 {header}", expanded=True):
                for line in lines[1:]:
                    if not line: continue
                    if ":" in line:
                        label,content=line.split(":",1)
                        label=label.strip(); content=content.strip()
                        keywords=[k.strip() for k in content.split(",") if k.strip()]
                        if keywords and ("키워드" in label or "태그" in label or "해시태그" in label):
                            copy_text=", ".join(keywords)
                            chips=" ".join([f'<span class="kw-chip">{k}</span>' for k in keywords])
                            # ★ st.download_button으로 복사 — clipboard API iframe 차단 우회
                            col_l,col_r=st.columns([5,1])
                            with col_l:
                                st.markdown(f'<div style="margin:.3rem 0"><b>{label}:</b><br>{chips}</div>',
                                            unsafe_allow_html=True)
                            with col_r:
                                st.download_button(
                                    label="📋",
                                    data=copy_text,
                                    file_name=f"{label.strip()}.txt",
                                    mime="text/plain",
                                    key=f"dl_{header}_{label}",
                                    help=f"클릭하면 {label} 다운로드 (내용: {copy_text[:50]}...)"
                                )
                        else:
                            st.markdown(f"**{label}:** {content}")
                    else:
                        st.markdown(line)

        # 전체 키워드 TXT 다운로드
        st.markdown("<br>",unsafe_allow_html=True)
        dl_kw,tg_kw,clr_kw=st.columns([2,2,1])
        with dl_kw:
            st.download_button("💾 전체 키워드 TXT 다운로드",data=result_text,
                               file_name=f"키워드_{kw_prod[:20]}.txt",mime="text/plain",
                               use_container_width=True)
        kw_tg_ph=st.empty()
        with tg_kw:
            if st.button("📱 키워드 텔레그램 전송",use_container_width=True,key="kw_tg"):
                ok_sent=send_tg_long(result_text,"🔑 키워드 생성 결과")
                if ok_sent: kw_tg_ph.success("✅ 전송 완료")
                else: kw_tg_ph.error("❌ 전송 실패")
        with clr_kw:
            if st.button("초기화",use_container_width=True,key="kw_clr"):
                st.session_state["kw_result"]=None; st.rerun()

# ══════════════════════════════════════════════════════════════
# TAB 4: AI 이미지 생성 (v9.0 가이드북 적용)
# ══════════════════════════════════════════════════════════════
with tab4:
    st.markdown("### 🎨 AI 상세페이지 이미지 프롬프트 생성")
    st.markdown("소싱레이더 AI 마스터 가이드북 v9.0 기준 | DALL-E 3 최적화 | 12개 이미지 | 860px 고정")

    with st.expander("📋 v9.0 12단계 이미지 규격 미리보기", expanded=False):
        spec_data=pd.DataFrame(IMAGE_SPEC)[["no","stage","kr","w","h"]]
        spec_data.columns=["번호","스테이지","섹션명","가로(px)","세로(px)"]
        st.dataframe(spec_data,use_container_width=True,hide_index=True)

    st.markdown('<div class="ai-section">',unsafe_allow_html=True)
    img_col1,img_col2=st.columns(2)
    with img_col1:
        img_brand=st.text_input("브랜드명",placeholder="예: 인터뷰어 토마토즙",key="img_brand")
        img_target=st.text_input("타겟 고객",placeholder="예: 20~40대 건강관리에 관심있는 직장인",key="img_target")
        img_category=st.selectbox("상품 카테고리",
                                  ["식품/음료","뷰티/화장품","패션/의류","생활용품",
                                   "디지털/가전","스포츠/레저","반려동물","기타"],key="img_category")
    with img_col2:
        img_url=st.text_input("참고 상품 URL (선택 — 실제 페이지 내용 자동 분석)",
                              placeholder="https://... 입력 시 AI가 페이지 내용 실제 참조",key="img_url")
        st.info("💡 톤앤매너는 AI가 상품/타겟 분석 후 자동 결정합니다 (v9.0 자동화 기준)")

    img_features=st.text_area("상품 주요 특징",
        placeholder="1. 국산 토마토 100% 사용\n2. NFC 착즙 방식\n3. 무첨가 원칙 ...",
        height=150,key="img_features")

    if st.button("🎨 12개 이미지 프롬프트 생성 (v9.0 가이드 적용)",type="primary",
                 use_container_width=True,
                 disabled=(not GEMINI_KEY or not img_brand or not img_features)):
        with st.spinner("v9.0 가이드북 기준으로 12개 DALL-E 3 프롬프트 설계 중... (20~40초)"):
            result=generate_image_prompts_v9(img_brand,img_url,img_features,img_target,img_category)
        st.session_state["img_prompt"]=result
    st.markdown('</div>',unsafe_allow_html=True)

    if st.session_state.get("img_prompt"):
        st.markdown("---")
        st.markdown("**🎨 12개 이미지 프롬프트 — DALL-E 3 최적화 (상단 40% 솔리드 배경 적용)**")
        st.caption("각 'DALL-E 3 Prompt:' 텍스트를 ChatGPT에 붙여넣고 '이 프롬프트로 이미지를 생성해줘'라고 입력하세요.")

        prompt_text=st.session_state["img_prompt"]

        # v9.0 이미지별 섹션 파싱
        image_blocks=_re.split(r"\[Image\s*(\d+)", prompt_text)
        if len(image_blocks)>1:
            idx=1
            while idx<len(image_blocks):
                num=image_blocks[idx]
                content=image_blocks[idx+1] if idx+1<len(image_blocks) else ""
                section_line=content.split("\n")[0].strip().strip(":").strip("]").strip()
                spec_match=[s for s in IMAGE_SPEC if s["no"]==int(num)] if num.isdigit() else []
                size_info=f" | {spec_match[0]['w']}×{spec_match[0]['h']}px" if spec_match else ""
                with st.expander(f"🖼 Image {num}: {section_line}{size_info}", expanded=False):
                    st.markdown(content)
                    # DALL-E 3 프롬프트 추출 → 복사용 코드블록
                    dalle_match=_re.search(r"DALL-E 3 Prompt:\s*\n?(Photorealistic[^\[]+)",content,_re.I|_re.S)
                    if dalle_match:
                        dalle_prompt=dalle_match.group(1).strip()
                        st.markdown("**📋 ChatGPT에 붙여넣을 DALL-E 3 프롬프트:**")
                        st.code(dalle_prompt,language=None)
                        st.download_button(
                            f"💾 Image {num} 프롬프트 저장",
                            data=f"이 프롬프트로 이미지를 생성해줘:\n\n{dalle_prompt}",
                            file_name=f"{img_brand}_{num:0>2}_{section_line[:10]}.txt",
                            mime="text/plain",
                            key=f"img_dl_{num}"
                        )
                idx+=2
        else:
            st.markdown(prompt_text)

        st.markdown("<br>",unsafe_allow_html=True)
        download_text=build_download_text(img_brand if img_brand else "상품", prompt_text)
        dl_col,tg_col,clr_col=st.columns([2,1.5,1])
        with dl_col:
            st.download_button("💾 전체 12개 프롬프트 TXT 다운로드",
                data=download_text,
                file_name=f"{img_brand if img_brand else '상품'}_상세페이지_프롬프트_v9.txt",
                mime="text/plain",use_container_width=True)
        img_tg_ph=st.empty()
        with tg_col:
            if st.button("📱 텔레그램 전송",use_container_width=True,key="img_tg"):
                ok_sent=send_tg_long(prompt_text,"🎨 상세페이지 이미지 프롬프트 v9.0")
                if ok_sent: img_tg_ph.success("✅ 전송 완료")
                else: img_tg_ph.error("❌ 전송 실패")
        with clr_col:
            if st.button("초기화",use_container_width=True,key="img_clr"):
                st.session_state["img_prompt"]=None; st.rerun()

        st.info("💡 ChatGPT 사용법: 각 이미지 프롬프트 복사 → ChatGPT(GPT-4o) 대화창 붙여넣기 "
                "→ '이 프롬프트로 이미지를 생성해줘' 입력 → 이미지 우클릭 → 이미지 저장\n"
                "ChatGPT 무료 계정: 하루 제한 있음 | Plus($20/월): 제한 없음")

# ══════════════════════════════════════════════════════════════
# TAB 5: 텔레그램
# ══════════════════════════════════════════════════════════════
with tab5:
    st.markdown("### 📱 텔레그램 알림 설정")
    col_a,col_b=st.columns(2)
    with col_a:
        st.markdown("""
봇 만들기
1. 텔레그램에서 @BotFather 검색
2. /newbot 입력 후 이름 설정
3. 발급된 토큰 복사

채팅방 ID 확인
https://api.telegram.org/bot[토큰]/getUpdates
chat.id 뒤 숫자가 본인 채팅방 ID

친구에게 전송하는 방법
친구가 봇에게 /start 메시지를 보내야 합니다.
그 후 위 URL에서 친구의 chat.id 확인 후 TELEGRAM_CHAT_IDS에 추가하세요.
        """)
    with col_b:
        st.markdown("Secrets 등록")
        st.code("""DOMEGGOOK_API_KEY  = "API키"
TELEGRAM_BOT_TOKEN = "봇토큰"
TELEGRAM_CHAT_ID   = "내 채팅방ID"
TELEGRAM_CHAT_IDS  = "내ID,친구ID"
GEMINI_API_KEY     = "제미나이키(무료)"
""",language="toml")
        st.info("💡 TELEGRAM_CHAT_IDS에 콤마로 여러 ID를 넣으면 모두에게 전송됩니다.\n"
                "친구의 ID는 getUpdates에서 확인: 로그의 chat.id = 922742140")
        test_msg=st.text_input("테스트 메시지",value="소싱레이더 연동 테스트")
        tg5_ph=st.empty()
        if st.button("테스트 발송",type="primary",use_container_width=True):
            ok=send_telegram_message(test_msg)
            if ok: tg5_ph.success("✅ 성공")
            else: tg5_ph.error("❌ 실패")

# ══════════════════════════════════════════════════════════════
# TAB 6: 가이드
# ══════════════════════════════════════════════════════════════
with tab6:
    st.markdown("### 📖 가이드")
    with st.expander("플랫폼별 수수료 (2025년 기준)"):
        st.markdown("""
| 플랫폼 | 적용 수수료 | 비고 |
|---|---|---|
| 네이버 스마트스토어 | 6% | 판매2.73%+결제3.3% |
| 쿠팡 | 11% | 카테고리별 4~10.8% |
| 11번가 | 12% | 카테고리별 6~13% |
| G마켓 | 12% | 카테고리별 4~15% |
| 옥션 | 12% | G마켓 동일 구조 |
        """)
    with st.expander("AI 이미지 생성 v9.0 — ChatGPT 사용 방법"):
        st.markdown("""
1. 소싱레이더에서 브랜드명/특징 입력 후 프롬프트 생성
2. 각 이미지의 DALL-E 3 Prompt 텍스트 복사 (📋 코드블록 클릭)
3. chatgpt.com 접속 → GPT-4o 선택
4. "이 프롬프트로 이미지를 생성해줘:" + 프롬프트 붙여넣기
5. 생성된 이미지 우클릭 → 이미지 저장
6. 파일명: {브랜드}_01_HOOK.png ... {브랜드}_12_CTA.png

v9.0 핵심: 상단 40% 솔리드 배경으로 텍스트 오버레이 공간 확보
        """)
    with st.expander("업체등급 확인 방법"):
        st.markdown("""
라이브 검색 후 🏅 업체등급 조회 버튼 클릭 (상위15개 상세 API 호출)
또는 ⭐ 관심 등록 시 즉시 상세 API 호출 → DB에 등급 영구 저장

Streamlit 로그(Manage app → Logs)에서 [상세 seller원문] 확인 가능
        """)
    with st.expander("온채널 — 클라우드 차단 안내"):
        st.markdown("""
온채널(onch3.co.kr)은 클라우드 서버 IP를 403으로 차단합니다.
도매매/도매꾹 검색은 정상 동작합니다.
온채널은 직접 사이트에서 확인하세요.
        """)
