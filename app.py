"""
소싱레이더 v9.0 — 완전 자동화 이커머스 관리 시스템
탭 구성:
  1. 라이브 검색
  2. 관심 상품
  3. 키워드 생성
  4. AI 이미지 생성
  5. 📊 시장 분석 (네이버 데이터랩 + 쿠팡)   ← 신규
  6. 🛒 상품 자동 등록                         ← 신규
  7. 📦 주문/송장 관리                         ← 신규
  8. 텔레그램
  9. 가이드
"""
import re as _re, time as _time, base64
import streamlit as st
import streamlit.components.v1 as components
import sqlite3, pandas as pd, requests as req
import plotly.express as px
from datetime import datetime, timedelta
from utils import calculate_target_price, calculate_expected_profit
from database import init_db, upsert_tracked_product
from domeme_client import DomeameClient
from notifications import send_telegram_message

st.set_page_config(layout="wide", page_title="소싱레이더", page_icon="📡",
                   initial_sidebar_state="expanded")
st.markdown("""<style>
.block-container{padding-top:1.2rem;padding-bottom:2rem;max-width:1500px}
.stApp{background:#F7F8FA}
.mh{background:linear-gradient(135deg,#1a1a2e,#0f3460);border-radius:16px;
    padding:1.5rem 2rem;margin-bottom:1.5rem}
.mh h1{font-size:1.8rem;font-weight:700;margin:0;color:white}
.mh p{font-size:.9rem;margin:.3rem 0 0;color:#94a3b8}
.kc{background:white;border-radius:12px;padding:1.2rem 1.4rem;
    border:1px solid #e2e8f0;box-shadow:0 1px 3px rgba(0,0,0,.06)}
.kl{font-size:.72rem;color:#64748b;font-weight:600;text-transform:uppercase;letter-spacing:.05em;margin-bottom:.3rem}
.kv{font-size:1.7rem;font-weight:700;color:#1e293b;line-height:1}
.ks{font-size:.72rem;color:#94a3b8;margin-top:.2rem}
section[data-testid="stSidebar"]{background:#1a1a2e !important}
section[data-testid="stSidebar"] *{color:#cbd5e1 !important}
.stButton>button{border-radius:8px !important;font-weight:600 !important}
.stTabs [data-baseweb="tab-list"]{gap:3px;background:#f1f5f9;border-radius:10px;padding:4px}
.stTabs [data-baseweb="tab"]{border-radius:8px !important;font-weight:500 !important;font-size:.82rem !important}
.stTabs [aria-selected="true"]{background:white !important;box-shadow:0 1px 3px rgba(0,0,0,.1) !important}
.kw-chip{display:inline-block;background:#EFF6FF;color:#1D4ED8;font-size:.78rem;
    padding:3px 10px;border-radius:20px;margin:2px;font-weight:500}
.img-check-row{display:flex;align-items:center;padding:8px 12px;border:1px solid #e2e8f0;
    border-radius:8px;margin-bottom:6px;background:white;gap:12px}
footer{visibility:hidden}
</style>""", unsafe_allow_html=True)

# ── Secrets ──────────────────────────────────────────────────
def _sec(k, d=""):
    try: return st.secrets.get(k, d)
    except: return d

DOME_KEY    = _sec("DOMEGGOOK_API_KEY")
GEMINI_KEY  = _sec("GEMINI_API_KEY")
NAV_ID      = _sec("NAVER_CLIENT_ID")
NAV_SECRET  = _sec("NAVER_CLIENT_SECRET")
CP_ACCESS   = _sec("COUPANG_ACCESS_KEY")
CP_SECRET   = _sec("COUPANG_SECRET_KEY")
CP_VENDOR   = _sec("COUPANG_VENDOR_ID")
GS_JSON     = _sec("GOOGLE_SERVICE_ACCOUNT_JSON")
GS_ID       = _sec("GOOGLE_SHEET_ID")

init_db()
client = DomeameClient(api_key=DOME_KEY) if DOME_KEY else None

# 선택적 클라이언트 초기화
naver_client = None
if NAV_ID and NAV_SECRET:
    try:
        from naver_client import NaverClient
        naver_client = NaverClient(NAV_ID, NAV_SECRET)
        INSIGHT_CATS = NaverClient.INSIGHT_CATEGORIES
    except: pass
else:
    INSIGHT_CATS = {}

coupang_client = None
if CP_ACCESS and CP_SECRET and CP_VENDOR:
    try:
        from coupang_client import CoupangClient
        coupang_client = CoupangClient(CP_ACCESS, CP_SECRET, CP_VENDOR)
    except: pass

sheets_manager = None
if GS_JSON and GS_ID:
    try:
        from sheets_client import SheetsManager
        sheets_manager = SheetsManager(GS_JSON, GS_ID)
    except: pass

# ── 상수 ─────────────────────────────────────────────────────
CATEGORY_MAP={
    "전체보기":{"전체보기":"0000"},
    "패션의류":{"전체보기":"01","여성의류":"0101","남성의류":"0102"},
    "패션잡화":{"전체보기":"02","신발":"0201","가방":"0202","화장품/미용":"0204"},
    "디지털/가전":{"전체보기":"04","음향가전":"0401","생활가전":"0402","계절가전":"0403"},
    "생활/건강":{"전체보기":"06","생활용품":"0601","건강/의료용품":"0602"},
    "식품":{"전체보기":"09","가공식품":"0901","건강식품":"0902","농축수산물":"0903"},
    "가구/인테리어":{"전체보기":"10","가구":"1001","인테리어소품":"1002"},
}
PLATFORM_FEE={"네이버 스마트스토어":0.06,"쿠팡":0.11,"11번가":0.12,"G마켓":0.12,"옥션":0.12}
MARGIN_MAP={"안정형  (10%)":0.10,"밸런스형 (20%)":0.20,"고마진형 (40%)":0.40}
FETCH_PRESETS={"빠른 탐색  (50개)":(50,1),"일반 검색  (100개)":(50,2),
               "심층 분석  (200개)":(50,4),"대량 수집  (500개)":(50,10)}
IMAGE_SPEC=[
    {"no":1,"stage":"HOOK","kr":"훅","h":2200,"desc":"3초 안에 시선 확보, 히어로 제품 샷"},
    {"no":2,"stage":"Painpoint","kr":"문제 공감","h":1800,"desc":"고객 문제 공감, 감정 자극"},
    {"no":3,"stage":"Solution","kr":"해결 제안","h":2000,"desc":"제품 등장, Before/After"},
    {"no":4,"stage":"USP1","kr":"핵심 가치 1","h":1800,"desc":"가장 강력한 차별화 포인트"},
    {"no":5,"stage":"USP2","kr":"핵심 가치 2","h":1800,"desc":"기능적 우수성 클로즈업"},
    {"no":6,"stage":"USP3","kr":"핵심 가치 3","h":1800,"desc":"성분/원재료 신뢰 강화"},
    {"no":7,"stage":"USP4","kr":"핵심 가치 4","h":1800,"desc":"감성/편의 라이프스타일"},
    {"no":8,"stage":"TPO","kr":"활용성","h":1800,"desc":"일상 다양한 사용 장면"},
    {"no":9,"stage":"Certification","kr":"신뢰","h":2500,"desc":"인증/품질 신뢰 구축"},
    {"no":10,"stage":"SpecsInfo","kr":"상세 정보","h":2800,"desc":"규격/성분 정보 표"},
    {"no":11,"stage":"Audience","kr":"추천 대상","h":1600,"desc":"구매자 매칭 페르소나"},
    {"no":12,"stage":"CTA","kr":"행동 유도","h":1800,"desc":"최종 구매 전환"},
]

for k,v in {"live_results":[],"show_results":False,"search_error":None,"page_num":0,
            "ai_result":None,"live_view":"card","mon_view":"card",
            "kw_result":None,"img_prompts":{},"img_checked":list(range(1,13)),
            "card_ai_selected":set(),"grade_cache":{}}.items():
    if k not in st.session_state: st.session_state[k]=v

# ── 헬퍼 ─────────────────────────────────────────────────────
def fmt_dt(s):
    if not s or str(s) in ("nan","None",""): return ""
    try: return datetime.strptime(str(s)[:19],"%Y-%m-%d %H:%M:%S").strftime("%y.%m.%d")
    except: return str(s)[:10]

def load_tracked():
    try:
        conn=sqlite3.connect("sourcing.db")
        df=pd.read_sql_query("SELECT * FROM products WHERE is_tracked=1 ORDER BY updated_at DESC",conn)
        conn.close()
        for col,d in [("seller_grade",""),("image_url","")]:
            if col not in df.columns: df[col]=d
        return df
    except: return pd.DataFrame()

def apply_margin(df,fee,mg):
    df=df.copy()
    df["추천 판매가(원)"]=df.apply(lambda r:calculate_target_price(r["supply_price"],r["delivery_fee"],fee,mg),axis=1)
    df["예상 순수익(원)"]=df.apply(lambda r:calculate_expected_profit(r["추천 판매가(원)"],r["supply_price"],r["delivery_fee"],fee),axis=1)
    df["마진율(%)"]=df.apply(lambda r:round(r["예상 순수익(원)"]/r["추천 판매가(원)"]*100,1) if r["추천 판매가(원)"]>0 else 0,axis=1)
    return df

def do_search():
    st.session_state.update({"search_error":None,"page_num":0,"live_results":[],"ai_result":None,"show_results":False,"card_ai_selected":set()})
    kw=st.session_state.get("search_kw","").strip()
    cat=CATEGORY_MAP[st.session_state["cat_main"]][st.session_state["cat_sub"]]
    sites=st.session_state.get("sourcing_sites",["도매매","도매꾹"])
    pg,mp=FETCH_PRESETS.get(st.session_state.get("fetch_preset","일반 검색  (100개)"),(50,2))
    results=[]; errs=[]
    if not DOME_KEY: errs.append("DOMEGGOOK_API_KEY 없음")
    elif client:
        try:
            if "도매매" in sites: results.extend(client.fetch_product_list(market="supply",keyword=kw,category_code=cat,page_size=pg,max_pages=mp))
            if "도매꾹" in sites: results.extend(client.fetch_product_list(market="dome",keyword=kw,category_code=cat,page_size=pg,max_pages=mp))
        except Exception as e: errs.append(str(e))
    if errs: st.session_state["search_error"]=" | ".join(errs)
    if not results and not errs: st.session_state["search_error"]="검색 결과 없음"
    elif results:
        df=pd.DataFrame(results).drop_duplicates(subset=["product_id"])
        for col,d in [("seller_grade",""),("image_url","")]:
            if col not in df.columns: df[col]=d
        cache=st.session_state["grade_cache"]
        df["seller_grade"]=df.apply(lambda r:cache.get(str(r["product_id"]),r["seller_grade"]),axis=1)
        st.session_state["live_results"]=df.to_dict("records")
    st.session_state["show_results"]=True

def reset_all():
    st.session_state.update({"search_kw":"","live_results":[],"show_results":False,
                              "search_error":None,"page_num":0,"ai_result":None,"card_ai_selected":set()})
    st.rerun()

def do_track(prod,is_track):
    if is_track and client and prod.get("site") in ["도매매","도매꾹"]:
        detail=client.fetch_item_detail(str(prod["product_id"]))
        if detail:
            for k,v in detail.items():
                if v or v==0: prod[k]=v
            if detail.get("seller_grade"):
                cache=st.session_state["grade_cache"]
                cache[str(prod["product_id"])]=detail["seller_grade"]
                st.session_state["grade_cache"]=cache
    upsert_tracked_product(prod,is_track)

def prod_url(row):
    site=row.get("site",""); pid=str(row.get("product_id",""))
    if site in ["도매꾹","도매매"]:
        mkt="" if site=="도매꾹" else "&market=supply"
        return f"https://domeggook.com/main/item/itemView.php?no={pid}{mkt}"
    return ""

def gc_color(grade):
    g=grade[0].upper() if grade and grade[0].isalpha() else ""
    return {"S":"#f59e0b","A":"#3b82f6","B":"#22c55e","C":"#eab308","D":"#f97316","E":"#ef4444"}.get(g,"#94a3b8")

def copy_btn(text,label="📋 복사"):
    s=text.replace("\\","\\\\").replace("`","\\`").replace("'","\\'").replace('"','\\"').replace("\n","\\n")
    return (f'<button onclick="var t=document.createElement(\'textarea\');t.value=\'{s}\';'
            f't.style.position=\'fixed\';t.style.opacity=\'0\';document.body.appendChild(t);'
            f't.focus();t.select();document.execCommand(\'copy\');document.body.removeChild(t);'
            f'this.textContent=\'✅ 복사됨\';setTimeout(()=>this.textContent=\'{label}\',2000);" '
            f'style="background:#3b82f6;color:white;border:none;border-radius:6px;'
            f'padding:6px 14px;font-size:.83rem;cursor:pointer;font-weight:600;width:100%">{label}</button>')

def render_cards(df,tracked_ids,pfx,on_toggle,show_ai=False,ai_set=None):
    for i in range(0,len(df),3):
        cols=st.columns(3)
        for ci,(_,row) in enumerate(df.iloc[i:i+3].iterrows()):
            with cols[ci]:
                cache=st.session_state["grade_cache"]
                grade=cache.get(str(row["product_id"]),str(row.get("seller_grade","")).strip())
                img=str(row.get("image_url","")).strip()
                profit=int(row.get("예상 순수익(원)",0)); sale=int(row.get("추천 판매가(원)",0))
                mp=float(row.get("마진율(%)",0)); pid=str(row["product_id"])
                is_t=pid in tracked_ids; url=prod_url(row); color=gc_color(grade)
                if img and img.startswith("http"):
                    link=f'<a href="{url}" target="_blank">' if url else ""
                    close="</a>" if url else ""
                    st.markdown(f'{link}<img src="{img}" style="width:100%;border-radius:8px;margin-bottom:6px"/>{close}',unsafe_allow_html=True)
                else:
                    a=f'href="{url}" target="_blank"' if url else ""
                    st.markdown(f'<a {a}><div style="height:90px;background:#f1f5f9;border-radius:8px;display:flex;align-items:center;justify-content:center;font-size:2.5rem;margin-bottom:6px">📦</div></a>',unsafe_allow_html=True)
                name_part=(f'<a href="{url}" target="_blank" style="color:#1e293b;text-decoration:none">{row["name"][:30]}</a>' if url else row["name"][:30])
                grade_part=(f'<span style="background:{color}22;color:{color};padding:2px 8px;border-radius:6px;font-size:.75rem;font-weight:600">{grade}</span>' if grade else '<span style="color:#94a3b8;font-size:.72rem">미조회</span>')
                st.markdown(f"""
<div style="font-size:.82rem;font-weight:500;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;margin-bottom:3px">{name_part}</div>
<div style="font-size:.7rem;color:#94a3b8;margin-bottom:3px">{row.get('site','')} | {pid}</div>
<div style="font-size:.75rem;color:#475569;margin-bottom:2px">공급가 <b>{int(row['supply_price']):,}원</b> 배송비 <b>{int(row['delivery_fee']):,}원</b></div>
<div style="font-size:.9rem;font-weight:700;color:#2563eb;margin-bottom:3px">판매가 {sale:,}원 &nbsp; 순수익 {profit:,}원</div>
<div style="font-size:.72rem;color:#64748b">마진 <b>{mp:.1f}%</b> &nbsp; 등급 {grade_part} &nbsp; {row.get('상태','')}</div>""",unsafe_allow_html=True)
                if show_ai and ai_set is not None:
                    checked=pid in ai_set
                    new=st.checkbox("🤖 AI분석 선택",value=checked,key=f"ai_{pfx}_{pid}")
                    if new!=checked:
                        if new: ai_set.add(pid)
                        else: ai_set.discard(pid)
                        st.session_state["card_ai_selected"]=ai_set
                if st.button("⭐ 등록됨" if is_t else "☆ 관심 등록",key=f"{pfx}_c_{pid}",use_container_width=True):
                    on_toggle(row.to_dict(),0 if is_t else 1); st.rerun()

def tg_long(text,prefix="📡"):
    chunks=[text[i:i+3800] for i in range(0,len(text),3800)]
    ok=True
    for i,c in enumerate(chunks):
        hdr=prefix if len(chunks)==1 else f"{prefix} ({i+1}/{len(chunks)})"
        if not send_telegram_message(f"{hdr}\n\n{c}"): ok=False
        if i<len(chunks)-1: _time.sleep(0.5)
    return ok

def gemini(prompt, max_tok=1500, retries=3):
    """Gemini 2.5 Flash Lite — 완전 무료 (토큰 제한 없음)"""
    if not GEMINI_KEY: return "GEMINI_API_KEY 미설정"
    for attempt in range(retries):
        try:
            r=req.post(
                f"https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash-lite:generateContent?key={GEMINI_KEY}",
                headers={"Content-Type":"application/json"},
                json={"contents":[{"parts":[{"text":prompt}]}],
                      "generationConfig":{"maxOutputTokens":max_tok,"temperature":0.15}},
                timeout=90)
            if r.status_code==200:
                return r.json()["candidates"][0]["content"]["parts"][0]["text"]
            if r.status_code==429:
                wait=20*(attempt+1)
                print(f"[429] {wait}초 대기")
                _time.sleep(wait); continue
            return f"오류 {r.status_code}"
        except Exception as e:
            if attempt<retries-1: _time.sleep(10); continue
            return f"AI 오류: {e}"
    return "Gemini 429 — 1분 후 재시도"

def gemini_vision(prompt, image_b64, max_tok=400):
    if not GEMINI_KEY: return ""
    try:
        r=req.post(
            f"https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash:generateContent?key={GEMINI_KEY}",
            headers={"Content-Type":"application/json"},
            json={"contents":[{"parts":[{"text":prompt},{"inline_data":{"mime_type":"image/jpeg","data":image_b64}}]}],
                  "generationConfig":{"maxOutputTokens":max_tok,"temperature":0.1}},
            timeout=60)
        if r.status_code==200:
            return r.json()["candidates"][0]["content"]["parts"][0]["text"]
    except: pass
    return ""

def compact_ai(df,fee,mg,pname,mname):
    rows=[]
    for _,r in df.iterrows():
        rows.append(f"{r['name'][:28]}({r.get('site','')})\n"
                    f"  원가{int(r.get('supply_price',0))+int(r.get('delivery_fee',0)):,}원 "
                    f"판가{int(r.get('추천 판매가(원)',0)):,}원 "
                    f"수익{int(r.get('예상 순수익(원)',0)):,}원 "
                    f"마진{r.get('마진율(%)',0):.1f}% 등급{r.get('seller_grade','미확인') or '미확인'}")
    return gemini(
        f"이커머스 소싱 전문가. 핵심만.\n판매:{pname} 수수료{int(fee*100)}%/목표마진{int(mg*100)}%\n"
        +"\n".join(rows)+
        "\n\n형식(이모티콘유지,줄앞-#*금지):\n🏆 즉시소싱TOP3\n1 상품명 이유\n2 상품명 이유\n3 상품명 이유\n"
        "❌ 제외권장\n상품명 이유\n📊 개별판정\n상품명 ✅/👍/⚠️/❌ 마진(상중하) 리스크 월50건수익원\n"
        "💡 이번달전략\n1 액션\n2 액션\n3 액션\n⚠️ 주의 2줄",1500)

def kw_gen(prod,feat,platforms):
    naver=[]; coupang=[]
    try:
        r=req.get("https://ac.shopping.naver.com/ac",
                  params={"q":prod,"st":1,"frm":"nv","r_format":"json","r_enc":"UTF-8"},
                  headers={"User-Agent":"Mozilla/5.0"},timeout=6)
        if r.status_code==200:
            data=r.json()
            items=data.get("items",[[]])[0] if data.get("items") else []
            naver=[i[0] for i in items[:10] if i]
    except: pass
    try:
        r=req.get("https://www.coupang.com/np/search/autoComplete",
                  params={"keyword":prod,"limit":10},
                  headers={"User-Agent":"Mozilla/5.0","Referer":"https://www.coupang.com/"},timeout=6)
        if r.status_code==200:
            coupang=[i.get("keyword","") for i in r.json().get("autoCompletes",[])[:10] if i.get("keyword")]
    except: pass
    realtime=""
    if naver: realtime+=f"\n네이버 인기검색어: {', '.join(naver)}"
    if coupang: realtime+=f"\n쿠팡 인기검색어: {', '.join(coupang)}"
    if not realtime: realtime="\n(실시간 수집 불가 — AI 분석 대체)"
    guides={"네이버 스마트스토어":"브랜드+상품유형+특징+타겟, 최대100자",
            "쿠팡":"핵심상품명+용량+특징, 최대50자",
            "11번가":"브랜드+상품명+규격+수량, 최대80자",
            "G마켓":"브랜드+유형+특징+구성, 최대80자",
            "옥션":"브랜드+유형+수량+혜택, 최대80자"}
    return gemini(
        f"이커머스 SEO 전문가.\n상품명:{prod}\n특징:{feat}\n실시간:{realtime}\n"
        +"\n".join([f"[{p}] {guides.get(p,'')}" for p in platforms])+
        "\n\n출력(##없이,---구분):\n[플랫폼명]\n추천 상품명: \n핵심 키워드: kw1, kw2, kw3, kw4, kw5\n"
        "롱테일 키워드: lt1, lt2, lt3\n태그: t1, t2, t3, t4, t5\n실시간 트렌드: \n등록 팁:\n---",2000)

def gen_img_prompt(spec, brand, features, target, category, image_b64=""):
    """
    이미지 1개 DALL-E 3 프롬프트 생성
    - DALL-E 3 영문 프롬프트 우선 생성 (토큰 충분히 확보)
    - 카피는 별도 간결하게
    - 이미지 업로드 시 패키지 시각 반영
    """
    pkg_desc = ""
    if image_b64:
        vq = ("Describe this product packaging in English (2-3 sentences max): "
              "1.Shape/size 2.Colors 3.Material. Brand: " + brand)
        analysis = gemini_vision(vq, image_b64, max_tok=200)
        if analysis and "오류" not in analysis:
            pkg_desc = " Product packaging: " + analysis.replace("\n"," ")

    stage_map = {
        "HOOK":          "hero product shot on premium lifestyle background, 3-second attention grab, dramatic lighting",
        "Painpoint":     "frustrated customer in everyday problem situation, no product shown, emotional empathy scene",
        "Solution":      "product dramatically revealed as solution, bright transformation from dark to light palette",
        "USP1":          "extreme close-up of product's key differentiating feature, sharp macro photography",
        "USP2":          "product being used in realistic functional context, benefit clearly demonstrated",
        "USP3":          "premium ingredient or raw material displayed artistically, scientific precision feel",
        "USP4":          "minimal lifestyle scene showing product's convenience and emotional satisfaction",
        "TPO":           "split scene showing product used in 3 different daily contexts: morning, office, outdoor",
        "Certification": "clean manufacturing facility background with quality seals displayed prominently",
        "SpecsInfo":     "clean white studio shot of product with organized specification grid layout around it",
        "Audience":      "three distinct lifestyle persona characters matched to product benefits",
        "CTA":           "complete product bundle arranged beautifully, premium hero shot with purchase urgency",
    }
    stage_dir = stage_map.get(spec["stage"], "premium commercial product photography")

    dalle_prompt = (
        "Photorealistic commercial photography, Naver Smartstore detail page image, "
        f"{brand} {category} product, {stage_dir}.{pkg_desc} "
        "The top 38% of the vertical canvas must be pure white (#FFFFFF), "
        "completely flat with zero textures, objects, or gradients, "
        "reserved for Korean headline and subheadline placement. "
        "Product occupies lower 62% of frame. "
        "Professional studio lighting, mobile-first single focal point, high contrast. "
        f"Target customer: {target if target else 'Korean adults 20-50'}. "
        "No text, no watermarks, no fake ratings. "
        f"860px width, {spec['h']}px height (tall vertical format). "
        "Generate ONE image only. "
        "Do not create collages. "
        "Do not create multi-panel layouts. "
        "Do not combine multiple sections into one canvas."
    )

    # 카피는 별도 짧게 생성 (토큰 효율)
    copy_result = gemini(
        f"스마트스토어 {spec['no']}번({spec['kr']}) 카피 (짧게):\n"
        f"상품:{brand}({category}) 특징:{features[:150]}\n"
        "메인카피(15-25자):\n서브카피(1문장):", max_tok=200)

    return (
        f"[Image {spec['no']:02d}: {spec['stage']} ({spec['kr']}) | 860×{spec['h']}px]\n\n"
        + copy_result.strip()
        + "\n\n---\n"
        f"DALL-E 3 Prompt (아래 내용 전체를 ChatGPT에 붙여넣기):\n"
        f"파일명: {spec['no']:02d}_{spec['stage']}.png 으로 저장하세요\n\n"
        "이 프롬프트로 이미지를 지금 바로 생성해줘:\n\n"
        + dalle_prompt
    )

# ── 사이드바 ─────────────────────────────────────────────────
with st.sidebar:
    st.markdown("## 📡 소싱레이더 v9.0")
    st.markdown("---")
    st.multiselect("소싱 업체",options=["도매매","도매꾹"],default=["도매매","도매꾹"],key="sourcing_sites")
    st.selectbox("검색 수량",list(FETCH_PRESETS.keys()),index=1,key="fetch_preset")
    st.markdown("#### 판매 전략")
    pname=st.selectbox("판매 플랫폼",list(PLATFORM_FEE.keys()))
    mname=st.select_slider("마진 전략",options=list(MARGIN_MAP.keys()))
    fee=PLATFORM_FEE[pname]; mg=MARGIN_MAP[mname]
    st.markdown(f"""<div style="background:#0f3460;border-radius:10px;padding:.8rem 1rem;margin-top:.5rem">
        <div style="color:#94a3b8;font-size:.72rem">현재 설정</div>
        <div style="color:white;font-size:1rem;font-weight:700">수수료 {int(fee*100)}% / 목표마진 {int(mg*100)}%</div>
        <div style="color:#64748b;font-size:.72rem">배수 ÷{round(1-fee-mg,2)}</div>
    </div>""",unsafe_allow_html=True)
    st.markdown("---")
    tdf=load_tracked(); ttl=len(tdf)
    ap=int(apply_margin(tdf,fee,mg)["예상 순수익(원)"].mean()) if not tdf.empty else 0
    st.markdown("#### 관심 상품")
    c1,c2=st.columns(2); c1.metric("등록",ttl); c2.metric("평균수익",f"{ap:,}원")
    st.markdown("---")
    # 연동 상태
    st.markdown("#### 연동 상태")
    for label,val in [("도매매/도매꾹","✅" if DOME_KEY else "❌"),
                       ("Gemini AI","✅" if GEMINI_KEY else "❌"),
                       ("네이버 API","✅" if naver_client else "❌"),
                       ("쿠팡 API","✅" if coupang_client else "❌"),
                       ("Google Sheets","✅" if sheets_manager else "❌"),
                       ("텔레그램","✅" if _sec("TELEGRAM_BOT_TOKEN") else "❌")]:
        st.markdown(f"{val} {label}")
    st.markdown("---")
    _sbph=st.empty()
    if st.button("📱 텔레그램 테스트",use_container_width=True):
        ok=send_telegram_message(f"소싱레이더 v9.0 연동 테스트\n관심상품 {ttl}개")
        if ok: _sbph.success("✅ 완료")
        else: _sbph.error("❌ 실패")
    st.caption("소싱레이더 v9.0 | Blueprint v9.1")

st.markdown("""<div class="mh">
    <h1>📡 소싱레이더 v9.0</h1>
    <p>도매매 · 도매꾹 실시간 분석 | 네이버/쿠팡 시장 분석 | 상품 자동 등록 | 주문 관리</p>
</div>""",unsafe_allow_html=True)

tab1,tab2,tab3,tab4,tab5,tab6,tab7,tab8,tab9,tab10=st.tabs([
    "🔍 라이브 검색","⭐ 관심 상품","🔑 키워드 생성","🎨 AI 이미지 생성",
    "📊 시장 분석","🛒 상품 등록","📦 주문/송장","📱 텔레그램","📖 가이드","📑 종합 리포트"])

# ══════════════════════════════════════════════════════════════
# TAB 1 — 라이브 검색
# ══════════════════════════════════════════════════════════════
with tab1:
    r1,r2,r3=st.columns([1.2,1.2,2.6])
    with r1: main_cat=st.selectbox("대분류",list(CATEGORY_MAP.keys()),key="cat_main")
    with r2: st.selectbox("중분류",list(CATEGORY_MAP[main_cat].keys()),key="cat_sub")
    with r3: st.text_input("키워드",key="search_kw",placeholder="예: 백팩, 텀블러...",on_change=do_search)
    b1,b2,b3,_=st.columns([1.5,1,1.2,2])
    with b1: st.button("검색",on_click=do_search,use_container_width=True,type="primary")
    with b2: st.button("초기화",on_click=reset_all,use_container_width=True)
    with b3:
        vs=st.selectbox("보기",["🖼 카드 보기","📋 표 보기"],key="lv_sel",label_visibility="collapsed")
        st.session_state["live_view"]="card" if "카드" in vs else "table"

    if st.session_state.get("search_error"): st.warning(st.session_state["search_error"])
    if not st.session_state["show_results"]:
        st.markdown("""<div style="text-align:center;padding:3rem 0;color:#94a3b8">
            <div style="font-size:3rem">📦</div>
            <div style="font-size:1rem;margin-top:.5rem">키워드를 입력하고 검색하세요</div>
            <div style="font-size:.8rem;margin-top:.3rem">⭐ 관심 등록 시 업체등급이 자동 조회됩니다</div>
        </div>""",unsafe_allow_html=True)
    else:
        raw=pd.DataFrame(st.session_state["live_results"])
        if raw.empty: st.info("검색 결과 없음")
        else:
            for col,d in [("seller_grade",""),("image_url","")]:
                if col not in raw.columns: raw[col]=d
            sc=raw["site"].value_counts().to_dict()
            st.markdown(f"<div style='color:#64748b;font-size:.85rem;margin-bottom:.5rem'>결과: "+" | ".join(f"{s} {n}개" for s,n in sc.items())+f" / 총 {len(raw):,}개</div>",unsafe_allow_html=True)

            fc1,fc2,fc3,fc4,fc5=st.columns([2,1,1,1.2,1.2])
            with fc1: kwf=st.text_input("재검색","",placeholder="상품명 필터...",label_visibility="collapsed")
            with fc2: sf=st.selectbox("소싱처",["전체"]+list(sc.keys()),label_visibility="collapsed")
            with fc3: stf=st.selectbox("상태",["전체","정상만"],label_visibility="collapsed")
            with fc4: sortc=st.selectbox("정렬",["예상 순수익(원)","공급가(원)","마진율(%)"],label_visibility="collapsed")
            with fc5: sorto=st.selectbox("순서",["높은순","낮은순"],label_visibility="collapsed")

            df=apply_margin(raw,fee,mg)
            df["상태"]=df["status"].apply(lambda x:"🟢 정상" if str(x)=="Y" else "❌ 품절")
            cache=st.session_state["grade_cache"]
            df["seller_grade"]=df.apply(lambda r:cache.get(str(r["product_id"]),r.get("seller_grade","")),axis=1)
            if kwf: df=df[df["name"].str.contains(kwf,case=False,na=False)]
            if sf!="전체": df=df[df["site"]==sf]
            if stf=="정상만": df=df[df["status"]=="Y"]
            df=df.sort_values(sortc,ascending=(sorto=="낮은순"))

            ok_cnt=len(df[df["status"]=="Y"])
            avgp=int(df[df["status"]=="Y"]["예상 순수익(원)"].mean()) if ok_cnt>0 else 0
            k1,k2,k3,k4=st.columns(4)
            k1.markdown(f'<div class="kc"><div class="kl">검색 결과</div><div class="kv">{len(df):,}</div><div class="ks">개</div></div>',unsafe_allow_html=True)
            k2.markdown(f'<div class="kc"><div class="kl">정상 판매</div><div class="kv" style="color:#16a34a">{ok_cnt:,}</div><div class="ks">개</div></div>',unsafe_allow_html=True)
            k3.markdown(f'<div class="kc"><div class="kl">평균 순수익</div><div class="kv">{avgp:,}</div><div class="ks">원/건</div></div>',unsafe_allow_html=True)
            k4.markdown(f'<div class="kc"><div class="kl">최고 순수익</div><div class="kv" style="color:#2563eb">{int(df["예상 순수익(원)"].max()) if len(df)>0 else 0:,}</div><div class="ks">원/건</div></div>',unsafe_allow_html=True)
            st.markdown("<br>",unsafe_allow_html=True)

            ds=50 if st.session_state["live_view"]=="table" else 18
            tpg=max(1,(len(df)+ds-1)//ds); pn=min(st.session_state["page_num"],tpg-1)
            pdf=df.iloc[pn*ds:(pn+1)*ds].copy()
            tids=load_tracked()["product_id"].astype(str).tolist()
            pdf["⭐ 관심"]=pdf["product_id"].astype(str).isin(tids)

            if st.session_state["live_view"]=="card":
                render_cards(pdf,tids,"lv",lambda p,t:do_track(p,t))
            else:
                sc2=["⭐ 관심","site","product_id","name","supply_price","delivery_fee","상태","추천 판매가(원)","예상 순수익(원)","마진율(%)","seller_grade"]
                disp=pdf[sc2].copy()
                disp.columns=["⭐ 관심","소싱업체","상품번호","상품명","공급가(원)","배송비(원)","상태","추천 판매가(원)","예상 순수익(원)","마진율(%)","업체등급"]
                ed=st.data_editor(disp,use_container_width=True,hide_index=True,key=f"le_{pn}",
                    column_config={"⭐ 관심":st.column_config.CheckboxColumn("⭐ 관심",width="small"),
                                   "상품명":st.column_config.TextColumn("상품명",width="large"),
                                   "공급가(원)":st.column_config.NumberColumn(format="%d원"),
                                   "배송비(원)":st.column_config.NumberColumn(format="%d원"),
                                   "추천 판매가(원)":st.column_config.NumberColumn(format="%d원"),
                                   "예상 순수익(원)":st.column_config.NumberColumn(format="%d원"),
                                   "마진율(%)":st.column_config.NumberColumn(format="%.1f%%")})
                chg=False
                for i in range(len(ed)):
                    if ed.iloc[i]["⭐ 관심"]!=disp.iloc[i]["⭐ 관심"]:
                        do_track(pdf.iloc[i].to_dict(),1 if ed.iloc[i]["⭐ 관심"] else 0); chg=True
                if chg: st.rerun()

            p1,p2,p3=st.columns([1,3,1])
            with p1:
                if st.button("이전",disabled=(pn==0),use_container_width=True): st.session_state["page_num"]=pn-1; st.rerun()
            with p2: st.markdown(f"<div style='text-align:center;color:#64748b;font-size:.85rem;padding-top:.5rem'>{pn+1}/{tpg} | 총 {len(df):,}개</div>",unsafe_allow_html=True)
            with p3:
                if st.button("다음",disabled=(pn>=tpg-1),use_container_width=True): st.session_state["page_num"]=pn+1; st.rerun()

# ══════════════════════════════════════════════════════════════
# TAB 2 — 관심 상품
# ══════════════════════════════════════════════════════════════
with tab2:
    tdf=load_tracked()
    if tdf.empty:
        st.info("⭐ 라이브 검색에서 관심 등록하세요")
    else:
        tm=len(tdf); tc=apply_margin(tdf,fee,mg)
        okm=len(tdf[tdf["status"]=="Y"]); avm=round(tc["마진율(%)"].mean(),1)
        avp=int(tc[tc["status"]=="Y"]["예상 순수익(원)"].mean()) if okm>0 else 0
        k1,k2,k3,k4=st.columns(4)
        k1.markdown(f'<div class="kc"><div class="kl">관심 상품</div><div class="kv">{tm}</div><div class="ks">개</div></div>',unsafe_allow_html=True)
        k2.markdown(f'<div class="kc"><div class="kl">정상 판매</div><div class="kv" style="color:#16a34a">{okm}</div><div class="ks">개</div></div>',unsafe_allow_html=True)
        k3.markdown(f'<div class="kc"><div class="kl">평균 마진율</div><div class="kv" style="color:#7c3aed">{avm:.1f}%</div><div class="ks"></div></div>',unsafe_allow_html=True)
        k4.markdown(f'<div class="kc"><div class="kl">월 예상수익(100건)</div><div class="kv" style="color:#2563eb">{avp*100:,}</div><div class="ks">원</div></div>',unsafe_allow_html=True)
        st.markdown("<br>",unsafe_allow_html=True)

        mv1,mv2,mv3=st.columns([2,1,1])
        with mv1: mf=st.text_input("검색","",placeholder="상품명 필터...",label_visibility="collapsed")
        with mv2: ms=st.selectbox("상태",["전체","정상만","품절만"],label_visibility="collapsed")
        with mv3:
            mvs=st.selectbox("보기",["🖼 카드 보기","📋 표 보기"],key="mv_sel",label_visibility="collapsed")
            st.session_state["mon_view"]="card" if "카드" in mvs else "table"

        mdf=tc.copy(); mdf["상태"]=mdf["status"].apply(lambda x:"🟢 정상" if str(x)=="Y" else "❌ 품절")
        for col,d in [("seller_grade",""),("image_url","")]:
            if col not in mdf.columns: mdf[col]=d
        cache=st.session_state["grade_cache"]
        mdf["seller_grade"]=mdf.apply(lambda r:cache.get(str(r["product_id"]),str(r["seller_grade"]).replace("nan","")),axis=1)
        if mf: mdf=mdf[mdf["name"].str.contains(mf,case=False,na=False)]
        if ms=="정상만": mdf=mdf[mdf["status"]=="Y"]
        elif ms=="품절만": mdf=mdf[mdf["status"]!="Y"]

        tids_m=mdf["product_id"].astype(str).tolist(); edm=None
        cai=st.session_state.get("card_ai_selected",set())

        if st.session_state["mon_view"]=="card":
            render_cards(mdf,tids_m,"mn",lambda p,t:(upsert_tracked_product(p,t),st.rerun()),show_ai=True,ai_set=cai)
        else:
            mr=mdf.reset_index(drop=True); mr["AI선택"]=False; mr["해제"]=True
            if "updated_at" in mr.columns: mr["등록일"]=mr["updated_at"].apply(fmt_dt)
            keep=["AI선택","해제","site","product_id","name","supply_price","delivery_fee","상태","추천 판매가(원)","예상 순수익(원)","마진율(%)","seller_grade","등록일"]
            md=mr[[c for c in keep if c in mr.columns]].copy()
            md=md.rename(columns={"site":"소싱업체","product_id":"상품번호","name":"상품명","supply_price":"공급가(원)","delivery_fee":"배송비(원)","seller_grade":"업체등급"})
            edm=st.data_editor(md,use_container_width=True,hide_index=True,key="te",
                column_config={"AI선택":st.column_config.CheckboxColumn("AI선택",width="small"),
                               "해제":st.column_config.CheckboxColumn("해제",default=True,width="small"),
                               "상품명":st.column_config.TextColumn("상품명",width="large"),
                               "공급가(원)":st.column_config.NumberColumn(format="%d원"),
                               "배송비(원)":st.column_config.NumberColumn(format="%d원"),
                               "추천 판매가(원)":st.column_config.NumberColumn(format="%d원"),
                               "예상 순수익(원)":st.column_config.NumberColumn(format="%d원"),
                               "마진율(%)":st.column_config.NumberColumn(format="%.1f%%")},
                disabled=[c for c in md.columns if c not in ["AI선택","해제"]])
            tc2=False
            for i in range(len(edm)):
                if not edm.iloc[i]["해제"]:
                    m2=mr[mr["product_id"]==edm.iloc[i]["상품번호"]]
                    if not m2.empty: upsert_tracked_product(m2.iloc[0].to_dict(),0); tc2=True
            if tc2: st.rerun()

        st.markdown("<br>",unsafe_allow_html=True)
        bc1,bc2=st.columns([1,1])
        _tp=st.empty()
        with bc1:
            if st.button("📱 텔레그램 전송",use_container_width=True):
                lines=[f"관심 상품\n전체{tm}개/정상{okm}개/평균마진{avm:.1f}%\n"]
                for _,row in tc.iterrows():
                    lines.append(f"{'O' if row['status']=='Y' else 'X'} {row['name'][:22]} {int(row['추천 판매가(원)']):,}원 수익{int(row['예상 순수익(원)']):,}원")
                ok=tg_long("\n".join(lines),"관심 상품 현황")
                if ok: _tp.success("✅ 전송 완료")
                else: _tp.error("❌ 실패")
        with bc2:
            if sheets_manager and st.button("📊 구글 시트 동기화",use_container_width=True):
                products_data=[{**row.to_dict(),"target_price":int(row["추천 판매가(원)"]),"margin_rate":row["마진율(%)"]}
                               for _,row in tc.iterrows()]
                ok=sheets_manager.sync_sourcing_products(products_data)
                if ok: _tp.success("✅ 시트 동기화 완료")
                else: _tp.error("❌ 시트 동기화 실패")

        st.markdown("---")
        st.markdown("#### 🤖 AI 소싱 분석")
        if not GEMINI_KEY:
            st.info("GEMINI_API_KEY를 Secrets에 등록하세요 (무료)")
        else:
            sc2=0; sdf=pd.DataFrame()
            if st.session_state["mon_view"]=="card":
                sp=st.session_state.get("card_ai_selected",set()); sc2=len(sp)
                if sc2>0: sdf=tc[tc["product_id"].astype(str).isin(sp)].copy()
                if sc2>0: st.success(f"{sc2}개 선택됨")
                else: st.info("카드에서 🤖 체크 후 분석 또는 전체 분석")
            elif edm is not None and "AI선택" in edm.columns:
                sr=edm[edm["AI선택"]==True]; sc2=len(sr)
                if sc2>0: sdf=tc[tc["product_id"].isin(sr["상품번호"].tolist())].copy()
                if sc2>0: st.success(f"{sc2}개 선택됨")
                else: st.info("표에서 AI선택 체크 후 분석 또는 전체 분석")
            ba1,ba2=st.columns([2,1])
            with ba1: ab1=st.button("✨ 선택 상품 AI 분석",type="primary",use_container_width=True,disabled=(sc2==0))
            with ba2: ab2=st.button("📊 전체 AI 분석",use_container_width=True)
            if ab2:
                with st.spinner("분석 중..."): result=compact_ai(tc,fee,mg,pname,mname)
                st.session_state["ai_result"]=result
            if ab1 and sc2>0:
                with st.spinner(f"{sc2}개 분석 중..."): result=compact_ai(apply_margin(sdf,fee,mg),fee,mg,pname,mname)
                st.session_state["ai_result"]=result
            if st.session_state.get("ai_result"):
                st.markdown("---"); st.markdown("**📊 AI 소싱 분석 결과**")
                rt=st.session_state["ai_result"]; st.markdown(rt)
                _aph=st.empty(); ac1,ac2=st.columns([2,1])
                with ac1:
                    if st.button("📱 텔레그램 전송",use_container_width=True,key="at"):
                        ok=tg_long(rt,"🤖 AI 소싱 분석")
                        if ok: _aph.success("✅ 완료")
                        else: _aph.error("❌ 실패")
                with ac2:
                    if st.button("초기화",use_container_width=True,key="ac"):
                        st.session_state["ai_result"]=None; st.rerun()

# ══════════════════════════════════════════════════════════════
# TAB 3 — 키워드 생성
# ══════════════════════════════════════════════════════════════
with tab3:
    st.markdown("### 🔑 플랫폼별 키워드 생성")
    st.caption("네이버·쿠팡 실시간 인기 검색어를 수집해 플랫폼 최적화 키워드를 자동 생성합니다.")
    with st.container(border=True):
        kp=st.text_input("상품명",placeholder="예: 냉동 딸기 2.72kg",key="kw_prod")
        kf=st.text_area("주요 특징 (선택)",placeholder="예: 베이킹용, 스무디용, 대용량",height=60,key="kw_feat")
        kpls=st.multiselect("플랫폼 선택",options=list(PLATFORM_FEE.keys()),
                            default=["네이버 스마트스토어","쿠팡"],key="kw_pls")
        if st.button("🔑 키워드 생성",type="primary",use_container_width=True,
                     disabled=(not GEMINI_KEY or not kp or not kpls)):
            with st.spinner("실시간 검색어 수집 + AI 최적화 중..."):
                result=kw_gen(kp,kf,kpls)
            st.session_state["kw_result"]=result

    if st.session_state.get("kw_result"):
        st.markdown("---"); st.markdown("**🔑 키워드 결과**")
        rt=st.session_state["kw_result"]
        kfi=st.text_input("결과 내 재검색","",placeholder="필터...",key="kw_fi")
        for sec in [s.strip() for s in rt.split("---") if s.strip()]:
            lines=[l.strip() for l in sec.split("\n") if l.strip()]
            if not lines: continue
            hdr=lines[0].replace("##","").strip().strip("[]").strip()
            if kfi and kfi.lower() not in sec.lower(): continue
            with st.expander(f"📍 {hdr}",expanded=True):
                for line in lines[1:]:
                    if ":" not in line: st.markdown(line); continue
                    lbl,cnt=line.split(":",1); lbl=lbl.strip(); cnt=cnt.strip()
                    kws=[k.strip() for k in cnt.split(",") if k.strip()]
                    if kws and ("키워드" in lbl or "태그" in lbl or "트렌드" in lbl):
                        chips=" ".join([f'<span class="kw-chip">{k}</span>' for k in kws])
                        cl,cr=st.columns([5,1])
                        with cl: st.markdown(f'<div><b>{lbl}:</b><br>{chips}</div>',unsafe_allow_html=True)
                        with cr: components.html(copy_btn(", ".join(kws),"📋 복사"),height=44)
                    else: st.markdown(f"**{lbl}:** {cnt}")
        dc,tc2_col,cc=st.columns([2,2,1])
        _tkph=st.empty()
        with dc: st.download_button("💾 TXT 다운로드",data=rt,file_name=f"키워드_{kp[:20]}.txt",mime="text/plain",use_container_width=True)
        with tc2_col:
            if st.button("📱 텔레그램 전송",use_container_width=True,key="kt"):
                ok=tg_long(rt,"🔑 키워드"); _tkph.success("✅") if ok else _tkph.error("❌")
        with cc:
            if st.button("초기화",use_container_width=True,key="kc"):
                st.session_state["kw_result"]=None; st.rerun()

# ══════════════════════════════════════════════════════════════
# TAB 4 — AI 이미지 생성 (전체 체크박스 리스트 UI)
# ══════════════════════════════════════════════════════════════
with tab4:
    st.markdown("### 🎨 AI 상세페이지 이미지 프롬프트 생성")
    st.caption("Blueprint v9.1 | Gemini 무료 | DALL-E 3 최적화 → ChatGPT에 붙여넣기")
    with st.container(border=True):
        ic1,ic2=st.columns(2)
        with ic1:
            ib=st.text_input("브랜드명 *",placeholder="예: 인터뷰어 토마토즙",key="ib")
            it=st.text_input("타겟 고객 (선택)",placeholder="예: 20~40대 건강관리 직장인",key="it")
            icat=st.selectbox("카테고리 *",["식품/음료","뷰티/화장품","패션/의류","생활용품","디지털/가전","스포츠/레저","기타"],key="icat")
        with ic2:
            iup_files=st.file_uploader("상품 이미지 업로드 (선택 — 다중 선택 가능, Gemini Vision 분석)",
                                 type=["jpg","jpeg","png","webp"],
                                 accept_multiple_files=True, key="iup")
            if iup_files:
                img_cols=st.columns(min(len(iup_files),4))
                for ci,f in enumerate(iup_files[:4]):
                    with img_cols[ci]: st.image(f,use_container_width=True,caption=f.name)
                st.caption(f"✅ {len(iup_files)}개 업로드됨 — Gemini Vision이 첫 번째 이미지를 기준으로 패키지 색상·형태를 분석합니다.")
        iff=st.text_area("상품 주요 특징 *",placeholder="1. 특징1\n2. 특징2\n3. 특징3",height=100,key="iff")

    # ★ 이미지 전체 체크박스 리스트 UI
    st.markdown("#### 생성할 이미지 선택")
    st.caption("전체 선택/해제 후 원하는 항목만 체크하세요. Gemini 무료 한도를 위해 1~4개씩 권장합니다.")

    col_sel, col_desel = st.columns([1,1])
    with col_sel:
        if st.button("☑️ 전체 선택", use_container_width=True, key="img_sel_all"):
            for s in IMAGE_SPEC:
                st.session_state[f"img_chk_{s['no']}"] = True
            st.rerun()
    with col_desel:
        if st.button("☐ 전체 해제", use_container_width=True, key="img_desel_all"):
            for s in IMAGE_SPEC:
                st.session_state[f"img_chk_{s['no']}"] = False
            st.rerun()

    new_checked = []
    cols_chk = st.columns(2)
    for i, spec in enumerate(IMAGE_SPEC):
        with cols_chk[i % 2]:
            # ★ key 기반 독립 체크박스 — 전체 해제 버튼과 충돌 없음
            default_val = st.session_state.get(f"img_chk_{spec['no']}", True)
            val = st.checkbox(
                f"**{spec['no']:02d}** — {spec['stage']} ({spec['kr']})  |  860×{spec['h']}px  |  {spec['desc']}",
                value=default_val, key=f"img_chk_{spec['no']}")
            if val:
                new_checked.append(spec["no"])

    sel_count = len(new_checked)
    if sel_count > 0:
        st.info(f"✅ {sel_count}개 선택됨 — 예상 소요 시간: 약 {sel_count*15}~{sel_count*25}초")

    if st.button(f"🎨 선택된 {sel_count}개 이미지 프롬프트 생성",type="primary",
                 use_container_width=True,
                 disabled=(not GEMINI_KEY or not ib or not iff or sel_count==0)):
        sel_specs=[s for s in IMAGE_SPEC if s["no"] in new_checked]
        image_b64=""
        iup_files_ref = st.session_state.get("iup", [])
        # file_uploader multi는 리스트 반환, 첫 번째 이미지로 Vision 분석
        _first_img = None
        if "iup" in st.session_state and st.session_state["iup"]:
            try: _first_img = st.session_state["iup"][0] if isinstance(st.session_state["iup"],list) else st.session_state["iup"]
            except: pass
        if _first_img:
            try: image_b64=base64.b64encode(_first_img.getvalue()).decode("utf-8")
            except: pass

        prog=st.progress(0,text="프롬프트 생성 시작...")
        existing=st.session_state.get("img_prompts",{})
        errors=[]
        for i,spec in enumerate(sel_specs):
            prog.progress(i/len(sel_specs),text=f"Image {spec['no']:02d}: {spec['stage']} ({spec['kr']}) 생성 중...")
            result=gen_img_prompt(spec,ib,iff,it,icat,image_b64)
            if "429" in result:
                st.warning(f"Image {spec['no']}: 429 한도. 60초 대기 후 재시도...")
                _time.sleep(60)
                result=gen_img_prompt(spec,ib,iff,it,icat,image_b64)
            if "오류" in result or "Error" in result:
                errors.append(f"Image {spec['no']}: {result[:50]}")
            existing[spec["no"]]=result
            if i<len(sel_specs)-1: _time.sleep(4)
        st.session_state["img_prompts"]=existing
        prog.progress(1.0,text=f"완료! {len(sel_specs)}개 생성")
        if errors: st.warning("일부 오류: "+"\n".join(errors))
        st.rerun()

    if st.session_state.get("img_prompts"):
        prompts=st.session_state["img_prompts"]
        st.markdown("---")
        st.markdown(f"**🎨 생성된 프롬프트 ({len(prompts)}개)**")
        st.caption("DALL-E 3 Prompt 전체를 복사 → ChatGPT(GPT-4o) 붙여넣기 → Enter")
        all_texts=[]
        for no in sorted(prompts.keys()):
            spec_info=next((s for s in IMAGE_SPEC if s["no"]==no),{"stage":"","kr":"","h":1800})
            content=prompts[no]; all_texts.append(content)
            with st.expander(f"🖼 Image {no:02d}: {spec_info['stage']} ({spec_info['kr']}) | 860×{spec_info['h']}px",expanded=False):
                st.markdown(content)
                dm=_re.search(r"이 프롬프트로 이미지를 생성해줘:\n\n(Photorealistic[^\[]*)",content,_re.S)
                if dm:
                    gpt_text="이 프롬프트로 이미지를 생성해줘:\n\n"+dm.group(1).strip()
                    st.markdown("**📋 ChatGPT 붙여넣기용:**")
                    st.code(gpt_text,language=None)
                    c1,c2=st.columns([1,1])
                    with c1: components.html(copy_btn(gpt_text,f"📋 복사"),height=44)
                    with c2: st.download_button("💾 저장",data=gpt_text,
                                                file_name=f"{ib}_{no:02d}_{spec_info['stage']}.txt",
                                                mime="text/plain",key=f"dl_{no}")
        st.markdown("<br>",unsafe_allow_html=True)
        all_dl=f"소싱레이더 AI Blueprint v9.1\n브랜드:{ib}\n생성일:{datetime.now().strftime('%Y.%m.%d %H:%M')}\n{'='*60}\n\n"+"\n\n".join(all_texts)
        d1,c2=st.columns([3,1])
        with d1: st.download_button("💾 전체 프롬프트 TXT 다운로드",data=all_dl,file_name=f"{ib}_상세페이지_v91.txt",mime="text/plain",use_container_width=True)
        with c2:
            if st.button("전체 초기화",use_container_width=True,key="ic"):
                st.session_state["img_prompts"]={};  st.rerun()

# ══════════════════════════════════════════════════════════════
# ══════════════════════════════════════════════════════════════
# ══════════════════════════════════════════════════════════════
# TAB 5 — 시장 분석 (dashboard.py 기반 v3)
# ══════════════════════════════════════════════════════════════
with tab5:
    st.markdown("### 📊 네이버 시장 분석")

    if not naver_client:
        st.warning("NAVER_CLIENT_ID, NAVER_CLIENT_SECRET을 Secrets에 등록하세요.")
        st.code("""NAVER_CLIENT_ID     = "네이버 Client ID"
NAVER_CLIENT_SECRET = "네이버 Client Secret"
""", language="toml")
        st.info("developers.naver.com → 애플리케이션 등록 → 검색 API + 데이터랩 추가")
    else:
        # ── 공통 설정 (상단) ────────────────────────────────
        with st.container(border=True):
            sc1, sc2 = st.columns([1.5, 1])
            with sc1:
                na_kw_raw = st.text_input(
                    "분석 키워드 (쉼표 구분, 최대 5개)",
                    placeholder="예: 냉동딸기, 블루베리, 딸기주스",
                    key="na_kw_raw")
                na_keywords = [k.strip() for k in na_kw_raw.split(",") if k.strip()][:5]
                if na_keywords:
                    st.caption(f"✅ 적용 키워드: {' | '.join(na_keywords)}")
            with sc2:
                today = datetime.now()
                date_range = st.date_input(
                    "분석 기간 직접 지정",
                    value=(today - timedelta(days=90), today),
                    max_value=today, key="na_date_range",
                    help="시즌별 비교도 가능 — 시작일·종료일 직접 선택")
                if isinstance(date_range, tuple) and len(date_range) == 2:
                    na_start = date_range[0].strftime("%Y-%m-%d")
                    na_end   = date_range[1].strftime("%Y-%m-%d")
                else:
                    na_start = (today - timedelta(days=90)).strftime("%Y-%m-%d")
                    na_end   = today.strftime("%Y-%m-%d")

        if not na_keywords:
            st.info("키워드를 입력하면 분석이 자동 시작됩니다.")
        else:
            # ── 자동 실행: 키워드 변경 시 세션 초기화 ───────
            prev_kw = st.session_state.get("na_prev_kw", [])
            if na_keywords != prev_kw:
                for k in ["na_shop_df","na_blog_df","na_cafe_df","na_news_df","na_ins_df","na_trend_df"]:
                    st.session_state.pop(k, None)
                for k in ["na_shop_page","na_blog_page","na_cafe_page","na_news_page"]:
                    st.session_state[k] = 1
                st.session_state["na_prev_kw"] = na_keywords

            # ── 워드클라우드 헬퍼 (한글 폰트 fallback) ─────
            def make_wordcloud(text, width=800, height=300):
                """한글 폰트 없어도 동작, 있으면 한글 표시"""
                if not text.strip():
                    return None
                font_candidates = [
                    "/usr/share/fonts/truetype/nanum/NanumGothic.ttf",
                    "/usr/share/fonts/truetype/noto/NotoSansCJK-Regular.ttc",
                    "/System/Library/Fonts/Supplemental/AppleGothic.ttf",
                ]
                font_path = None
                import os
                for fp in font_candidates:
                    if os.path.exists(fp):
                        font_path = fp
                        break
                try:
                    from wordcloud import WordCloud
                    kwargs = dict(width=width, height=height,
                                  background_color="white", max_words=80,
                                  collocations=False)
                    if font_path:
                        kwargs["font_path"] = font_path
                    wc = WordCloud(**kwargs).generate(text)
                    return wc.to_array()
                except Exception as e:
                    print(f"[WordCloud] {e}")
                    return None

            # ── 서브탭 구성 ──────────────────────────────────
            nst1,nst2,nst3,nst4,nst5,nst6,nst7 = st.tabs([
                "📈 트렌드 비교","🛍️ 실시간 쇼핑","📝 블로그",
                "☕ 카페","📰 뉴스","📊 쇼핑인사이트","📑 종합 리포트"])

            # ══ NST1: 트렌드 비교 ══════════════════════════
            with nst1:
                st.markdown(f"#### 📈 검색어 트렌드 ({na_start} ~ {na_end})")
                tc1,tc2,tc3 = st.columns(3)
                with tc1:
                    analysis_mode = st.radio("분석 모드",["일반 트렌드","성별 비교"],horizontal=True,key="na_mode")
                with tc2:
                    time_unit_map={"일별":"date","주별":"week","월별":"month"}
                    na_tu = time_unit_map[st.selectbox("집계 단위",list(time_unit_map.keys()),key="na_tu")]
                with tc3:
                    gender_opt=""
                    if analysis_mode=="일반 트렌드":
                        g_sel=st.radio("성별",["전체","남성","여성"],horizontal=True,key="na_gender")
                        gender_opt={"전체":"","남성":"m","여성":"f"}[g_sel]
                    else:
                        st.info("남성 vs 여성 비교 모드")

                age_options=["0~12세","13~18세","19~24세","25~29세","30~34세","35~39세","40~44세","45~49세","50~54세","55~59세","60세 이상"]
                age_codes=[str(i+1) for i in range(11)]
                age_ref=dict(zip(age_options,age_codes))
                sel_ages=st.multiselect("연령대",age_options,placeholder="전체 연령",key="na_ages")
                sel_age_codes=[age_ref[a] for a in sel_ages]

                if st.button("📊 트렌드 분석",type="primary",use_container_width=True,key="na_trend_btn"):
                    with st.spinner("트렌드 데이터 수집 중..."):
                        if analysis_mode=="일반 트렌드":
                            df_t=naver_client.datalab_trend(na_keywords,na_start,na_end,na_tu,gender_opt,sel_age_codes)
                            st.session_state["na_trend_df"]=df_t
                            st.session_state["na_trend_mode"]="일반"
                        else:
                            dm=naver_client.datalab_trend(na_keywords,na_start,na_end,na_tu,"m",sel_age_codes)
                            df_f=naver_client.datalab_trend(na_keywords,na_start,na_end,na_tu,"f",sel_age_codes)
                            if not dm.empty: dm["gender"]="남성"
                            if not df_f.empty: df_f["gender"]="여성"
                            parts=[d for d in [dm,df_f] if not d.empty]
                            st.session_state["na_trend_df"]=pd.concat(parts) if parts else pd.DataFrame()
                            st.session_state["na_trend_mode"]="성별"

                df_t=st.session_state.get("na_trend_df",pd.DataFrame())
                mode_t=st.session_state.get("na_trend_mode","일반")
                if not df_t.empty:
                    df_t["period"]=pd.to_datetime(df_t["period"])
                    st.info(f"총 {len(df_t):,}개 데이터 포인트")
                    if mode_t=="일반":
                        fig=px.line(df_t,x="period",y="ratio",color="keyword",title="검색 트렌드 추이",markers=True)
                    else:
                        fig=px.line(df_t,x="period",y="ratio",color="keyword",facet_col="gender",title="성별 검색 트렌드 비교",markers=True)
                        fig.for_each_annotation(lambda a:a.update(text=a.text.split("=")[-1]))
                    fig.update_layout(hovermode="x unified")
                    st.plotly_chart(fig,use_container_width=True)

                    tr1,tr2=st.columns(2)
                    with tr1:
                        peak_data=[]
                        for kw in df_t["keyword"].unique():
                            kd=df_t[df_t["keyword"]==kw]
                            pr=kd.sort_values("ratio",ascending=False).iloc[0]
                            r7=kd.sort_values("period").tail(7)["ratio"].mean()
                            avg=kd["ratio"].mean()
                            peak_data.append({"키워드":kw,"피크날짜":pr["period"].strftime("%Y-%m-%d"),
                                              "피크지수":round(float(pr["ratio"]),1),
                                              "최근7일평균":round(r7,1),"전체대비(%)":round((r7-avg)/avg*100,1) if avg>0 else 0})
                        st.markdown("**🔥 키워드별 피크 & 최근 추세**")
                        st.dataframe(pd.DataFrame(peak_data),use_container_width=True,hide_index=True)
                    with tr2:
                        stats=[]
                        for kw in df_t["keyword"].unique():
                            r=df_t[df_t["keyword"]==kw]["ratio"]
                            stats.append({"키워드":kw,"평균":round(r.mean(),1),"최솟값":round(r.min(),1),"최댓값":round(r.max(),1),"표준편차":round(r.std(),1)})
                        st.markdown("**📊 기술 통계**")
                        st.dataframe(pd.DataFrame(stats),use_container_width=True,hide_index=True)

                    st.download_button("📥 트렌드 CSV",data=df_t.to_csv(index=False).encode("utf-8-sig"),file_name=f"trend_{na_start}_{na_end}.csv",mime="text/csv")

            # ══ NST2: 실시간 쇼핑 ══════════════════════════
            with nst2:
                st.markdown("#### 🛍️ 네이버 쇼핑 실시간 분석")
                sh_c1,sh_c2,sh_c3=st.columns(3)
                with sh_c1: sh_sort_val={"정확도순":"sim","최신순":"date","가격낮은순":"asc","가격높은순":"dsc"}[st.selectbox("정렬",["정확도순","최신순","가격낮은순","가격높은순"],key="sh_sort")]
                with sh_c2: sh_kw_filter=st.selectbox("키워드 필터",["전체"]+na_keywords,key="sh_kw_filter")
                with sh_c3: sh_view=st.radio("보기",["카드(4열)","리스트"],horizontal=True,key="sh_view")

                # ★ 자동 실행
                if "na_shop_df" not in st.session_state:
                    with st.spinner("쇼핑 데이터 수집 중..."):
                        st.session_state["na_shop_df"]=naver_client.search_shopping(na_keywords,display=100,sort="sim")
                        st.session_state["na_shop_page"]=1
                if st.button("🔄 새로고침",key="sh_btn"):
                    with st.spinner("쇼핑 데이터 수집 중..."):
                        st.session_state["na_shop_df"]=naver_client.search_shopping(na_keywords,display=100,sort=sh_sort_val)
                        st.session_state["na_shop_page"]=1

                df_s=st.session_state.get("na_shop_df",pd.DataFrame())
                if not df_s.empty:
                    disp_s=df_s[df_s["search_keyword"]==sh_kw_filter].copy() if sh_kw_filter!="전체" else df_s.copy()
                    m1,m2,m3=st.columns(3)
                    m1.metric("수집 상품",f"{len(disp_s)}개")
                    m2.metric("평균가",f"{int(disp_s['lprice'].mean()):,}원" if disp_s['lprice'].sum()>0 else "-")
                    m3.metric("활성 판매처",f"{disp_s['mall_name'].nunique()}개")

                    ch1,ch2=st.columns(2)
                    with ch1:
                        if disp_s["lprice"].sum()>0:
                            fig_box=px.box(disp_s,x="search_keyword",y="lprice",color="search_keyword",title="키워드별 가격 분포",labels={"lprice":"최저가(원)","search_keyword":"키워드"})
                            st.plotly_chart(fig_box,use_container_width=True)
                    with ch2:
                        mall_cnt=disp_s["mall_name"].value_counts().head(10).reset_index()
                        mall_cnt.columns=["판매처","상품수"]
                        fig_mall=px.bar(mall_cnt,x="상품수",y="판매처",orientation="h",title="판매처별 상품 노출 TOP10",color="상품수",color_continuous_scale="Blues")
                        st.plotly_chart(fig_mall,use_container_width=True)

                    st.divider()
                    PAGE_SZ=12 if "카드" in sh_view else 20
                    total_pg=max(1,(len(disp_s)-1)//PAGE_SZ+1)
                    pg=min(st.session_state.get("na_shop_page",1),total_pg)
                    pn1,pn2,pn3=st.columns([1,3,1])
                    with pn1:
                        if st.button("이전",key="sh_prev",disabled=(pg<=1)):
                            st.session_state["na_shop_page"]=pg-1; st.rerun()
                    with pn2: st.markdown(f"<div style='text-align:center;padding-top:.5rem'>{pg}/{total_pg} | 총 {len(disp_s)}개</div>",unsafe_allow_html=True)
                    with pn3:
                        if st.button("다음",key="sh_next",disabled=(pg>=total_pg)):
                            st.session_state["na_shop_page"]=pg+1; st.rerun()

                    page_df=disp_s.iloc[(pg-1)*PAGE_SZ:pg*PAGE_SZ]
                    if "카드" in sh_view:
                        for i in range(0,len(page_df),4):
                            cols=st.columns(4)
                            for ci,(_,row) in enumerate(page_df.iloc[i:i+4].iterrows()):
                                with cols[ci]:
                                    if row.get("image") and str(row["image"]).startswith("http"):
                                        st.markdown(f'<a href="{row["link"]}" target="_blank"><img src="{row["image"]}" style="width:100%;border-radius:8px;cursor:pointer;margin-bottom:4px"/></a>',unsafe_allow_html=True)
                                    st.markdown(f'<div style="font-size:.82rem;font-weight:500;overflow:hidden;text-overflow:ellipsis;white-space:nowrap"><a href="{row["link"]}" target="_blank" style="color:#1e293b;text-decoration:none">{row["title"][:28]}</a></div>',unsafe_allow_html=True)
                                    st.markdown(f'<div style="font-size:.88rem;color:#2563eb;font-weight:700">{int(row["lprice"]):,}원</div>',unsafe_allow_html=True)
                                    st.caption(f"🏪 {row['mall_name']}")
                    else:
                        for _,row in page_df.iterrows():
                            lc1,lc2=st.columns([1,4])
                            with lc1:
                                if row.get("image") and str(row["image"]).startswith("http"):
                                    st.markdown(f'<a href="{row["link"]}" target="_blank"><img src="{row["image"]}" style="width:100%;border-radius:6px"/></a>',unsafe_allow_html=True)
                            with lc2:
                                st.markdown(f"**[{row['title']}]({row['link']})**")
                                st.write(f"💰 최저가: **{int(row['lprice']):,}원** | 🏪 {row['mall_name']} | 📁 {row['category1']}")
                            st.divider()
                    st.download_button("📥 쇼핑 CSV",data=df_s.to_csv(index=False).encode("utf-8-sig"),file_name="shop.csv",mime="text/csv")

            # ══ NST3: 블로그 ══════════════════════════════
            with nst3:
                st.markdown("#### 📝 실시간 블로그 분석")
                # ★ 자동 실행
                if "na_blog_df" not in st.session_state:
                    with st.spinner("블로그 데이터 수집 중..."):
                        st.session_state["na_blog_df"]=naver_client.search_blog(na_keywords,display=100)
                        st.session_state["na_blog_page"]=1
                if st.button("🔄 새로고침",key="blog_btn"):
                    with st.spinner("블로그 데이터 수집 중..."):
                        st.session_state["na_blog_df"]=naver_client.search_blog(na_keywords,display=100)
                        st.session_state["na_blog_page"]=1

                df_bl=st.session_state.get("na_blog_df",pd.DataFrame())
                if not df_bl.empty:
                    df_bl=df_bl.copy()
                    # postdate 파싱 (YYYYMMDD 또는 YYYY-MM-DD 등)
                    def parse_pd(s):
                        if not s: return pd.NaT
                        s=str(s).strip()
                        for fmt in ["%Y%m%d","%Y-%m-%d","%Y. %m. %d."]:
                            try: return pd.to_datetime(s,format=fmt)
                            except: pass
                        try: return pd.to_datetime(s)
                        except: return pd.NaT
                    df_bl["postdate_dt"]=df_bl["postdate"].apply(parse_pd)
                    st.metric("수집된 블로그 문서",f"{len(df_bl):,}건")

                    # ① 키워드별 최근 블로그 게시물 분포 (라인 차트)
                    valid_bl=df_bl[df_bl["postdate_dt"].notna()].copy()
                    if not valid_bl.empty:
                        blog_daily=valid_bl.groupby(["postdate_dt","search_keyword"]).size().reset_index(name="content_count")
                        fig_bl=px.line(blog_daily,x="postdate_dt",y="content_count",color="search_keyword",
                                       title="키워드별 최근 블로그 게시물 분포",markers=True,
                                       labels={"postdate_dt":"작성일","content_count":"게시물 수","search_keyword":"키워드"})
                        st.plotly_chart(fig_bl,use_container_width=True)
                    else:
                        # 날짜 파싱 실패 시 키워드별 건수 바 차트
                        cnt_bl=df_bl["search_keyword"].value_counts().reset_index()
                        cnt_bl.columns=["키워드","건수"]
                        st.plotly_chart(px.bar(cnt_bl,x="키워드",y="건수",color="키워드",title="키워드별 블로그 포스팅 수"),use_container_width=True)

                    bc1,bc2=st.columns(2)
                    with bc1:
                        # ② 주요 활동 블로거 TOP10
                        if "bloggername" in df_bl.columns and df_bl["bloggername"].notna().any():
                            top_bl=df_bl[df_bl["bloggername"]!=""].groupby("bloggername").size().reset_index(name="건수").sort_values("건수",ascending=False).head(10)
                            if not top_bl.empty:
                                fig_bl2=px.bar(top_bl,x="건수",y="bloggername",orientation="h",
                                               title="🏆 주요 활동 블로거 TOP10",
                                               color="건수",color_continuous_scale="Magma")
                                st.plotly_chart(fig_bl2,use_container_width=True)
                    with bc2:
                        # ③ 블로그 제목 핵심 단어
                        from collections import Counter
                        all_bl_titles=" ".join(df_bl["title"].dropna().tolist())
                        stop=[w for w in na_keywords]+["있는","있는것","이번","하는","하면","그리고","이","가","을","을","는","에","와","의","도"]
                        bl_words=[w for w in all_bl_titles.split() if len(w)>1 and w not in stop]
                        wc_bl=Counter(bl_words).most_common(12)
                        if wc_bl:
                            df_bl_wc=pd.DataFrame(wc_bl,columns=["단어","빈도"])
                            fig_bl_wc=px.bar(df_bl_wc,x="단어",y="빈도",color="빈도",title="블로그 제목 핵심 단어",color_continuous_scale="PuRd",text_auto=True)
                            st.plotly_chart(fig_bl_wc,use_container_width=True)

                    # ④ 워드클라우드
                    st.markdown("**☁️ 블로그 이슈 워드클라우드**")
                    wc_img=make_wordcloud(all_bl_titles)
                    if wc_img is not None:
                        st.image(wc_img,use_container_width=True,caption="Blog Word Cloud")
                    else:
                        # fallback: 상위 키워드 표시
                        st.markdown(" ".join([f'`{w}({c})`' for w,c in Counter(bl_words).most_common(20)]))

                    st.divider()
                    # ⑤ 콘텐츠 통합 리스트
                    st.markdown("**📖 최근 블로그 콘텐츠 통합 리스트**")
                    pg_bl=st.session_state.get("na_blog_page",1)
                    sorted_bl=df_bl.sort_values("postdate_dt",ascending=False) if "postdate_dt" in df_bl.columns else df_bl
                    total_bl=max(1,(len(sorted_bl)-1)//20+1)
                    pg_bl=min(pg_bl,total_bl)
                    pn1,pn2,pn3=st.columns([1,3,1])
                    with pn1:
                        if st.button("이전",key="bl_prev",disabled=(pg_bl<=1)):
                            st.session_state["na_blog_page"]=pg_bl-1; st.rerun()
                    with pn2: st.markdown(f"<div style='text-align:center;padding-top:.5rem'>{pg_bl}/{total_bl}</div>",unsafe_allow_html=True)
                    with pn3:
                        if st.button("다음",key="bl_next",disabled=(pg_bl>=total_bl)):
                            st.session_state["na_blog_page"]=pg_bl+1; st.rerun()
                    show_cols=["search_keyword","title","bloggername","postdate_dt","link"]
                    show_cols=[c for c in show_cols if c in sorted_bl.columns]
                    col_cfg={"search_keyword":st.column_config.TextColumn("키워드"),"title":st.column_config.TextColumn("제목",width="large"),"bloggername":st.column_config.TextColumn("블로거"),"postdate_dt":st.column_config.DateColumn("작성일",format="YYYY-MM-DD"),"link":st.column_config.LinkColumn("링크",display_text="바로가기")}
                    st.dataframe(sorted_bl[show_cols].iloc[(pg_bl-1)*20:pg_bl*20],column_config=col_cfg,use_container_width=True,hide_index=True)
                    st.download_button("📥 블로그 CSV",data=df_bl.to_csv(index=False).encode("utf-8-sig"),file_name="blog.csv",mime="text/csv")

            # ══ NST4: 카페 ════════════════════════════════
            with nst4:
                st.markdown("#### ☕ 실시간 카페 분석")
                if "na_cafe_df" not in st.session_state:
                    with st.spinner("카페 데이터 수집 중..."):
                        st.session_state["na_cafe_df"]=naver_client.search_cafe(na_keywords,display=100)
                        st.session_state["na_cafe_page"]=1
                if st.button("🔄 새로고침",key="cafe_btn"):
                    with st.spinner("카페 데이터 수집 중..."):
                        st.session_state["na_cafe_df"]=naver_client.search_cafe(na_keywords,display=100)
                        st.session_state["na_cafe_page"]=1

                df_ca=st.session_state.get("na_cafe_df",pd.DataFrame())
                if not df_ca.empty:
                    st.metric("수집된 카페 게시글",f"{len(df_ca):,}건")
                    ca1,ca2=st.columns(2)
                    with ca1:
                        cafe_kw=df_ca["search_keyword"].value_counts().reset_index(); cafe_kw.columns=["키워드","게시물 수"]
                        st.plotly_chart(px.bar(cafe_kw,x="게시물 수",y="키워드",orientation="h",title="키워드별 카페 활동량 비교",color="키워드",color_discrete_sequence=px.colors.qualitative.Pastel),use_container_width=True)
                    with ca2:
                        if "cafename" in df_ca.columns:
                            top_ca=df_ca[df_ca["cafename"]!=""]["cafename"].value_counts().head(10).reset_index(); top_ca.columns=["카페명","게시물 수"]
                            if not top_ca.empty:
                                st.plotly_chart(px.bar(top_ca,x="게시물 수",y="카페명",orientation="h",title="🏆 주요 활동 카페 TOP10",color="게시물 수",color_continuous_scale="Viridis"),use_container_width=True)
                    from collections import Counter
                    all_ca_t=" ".join(df_ca["title"].dropna().tolist())
                    stop_ca=[w for w in na_keywords]+["있는","이번","하는","그리고","이","가","을","는","에","의","도"]
                    ca_words=[w for w in all_ca_t.split() if len(w)>1 and w not in stop_ca]
                    ca_wc=Counter(ca_words).most_common(15)
                    if ca_wc:
                        df_ca_wc=pd.DataFrame(ca_wc,columns=["단어","빈도"])
                        st.plotly_chart(px.bar(df_ca_wc,x="단어",y="빈도",color="빈도",title="카페 게시글 핵심 키워드 (TOP15)",color_continuous_scale="Blues",text_auto=True),use_container_width=True)
                    st.markdown("**☁️ 카페 이슈 워드클라우드**")
                    wc_ca=make_wordcloud(all_ca_t)
                    if wc_ca is not None: st.image(wc_ca,use_container_width=True,caption="Cafe Word Cloud")
                    else: st.markdown(" ".join([f'`{w}({c})`' for w,c in Counter(ca_words).most_common(20)]))
                    st.divider()
                    st.markdown("**👥 최신 통합 카페 게시물**")
                    pg_ca=st.session_state.get("na_cafe_page",1)
                    total_ca=max(1,(len(df_ca)-1)//20+1); pg_ca=min(pg_ca,total_ca)
                    pn1,pn2,pn3=st.columns([1,3,1])
                    with pn1:
                        if st.button("이전",key="ca_prev",disabled=(pg_ca<=1)):
                            st.session_state["na_cafe_page"]=pg_ca-1; st.rerun()
                    with pn2: st.markdown(f"<div style='text-align:center;padding-top:.5rem'>{pg_ca}/{total_ca}</div>",unsafe_allow_html=True)
                    with pn3:
                        if st.button("다음",key="ca_next",disabled=(pg_ca>=total_ca)):
                            st.session_state["na_cafe_page"]=pg_ca+1; st.rerun()
                    ca_cols=[c for c in ["search_keyword","title","cafename","link"] if c in df_ca.columns]
                    st.dataframe(df_ca[ca_cols].iloc[(pg_ca-1)*20:pg_ca*20],
                        column_config={"search_keyword":st.column_config.TextColumn("키워드"),"title":st.column_config.TextColumn("제목",width="large"),"cafename":st.column_config.TextColumn("카페명"),"link":st.column_config.LinkColumn("링크",display_text="바로가기")},
                        use_container_width=True,hide_index=True)
                    st.download_button("📥 카페 CSV",data=df_ca.to_csv(index=False).encode("utf-8-sig"),file_name="cafe.csv",mime="text/csv")

            # ══ NST5: 뉴스 ════════════════════════════════
            with nst5:
                st.markdown("#### 📰 실시간 뉴스 분석")
                if "na_news_df" not in st.session_state:
                    with st.spinner("뉴스 데이터 수집 중..."):
                        st.session_state["na_news_df"]=naver_client.search_news(na_keywords,display=100)
                        st.session_state["na_news_page"]=1
                if st.button("🔄 새로고침",key="news_btn"):
                    with st.spinner("뉴스 데이터 수집 중..."):
                        st.session_state["na_news_df"]=naver_client.search_news(na_keywords,display=100)
                        st.session_state["na_news_page"]=1

                df_nw=st.session_state.get("na_news_df",pd.DataFrame())
                if not df_nw.empty:
                    df_nw2=df_nw.copy()
                    df_nw2["pubDate"]=pd.to_datetime(df_nw2["pubDate"],errors="coerce")
                    st.metric("수집된 뉴스 기사",f"{len(df_nw2):,}건")
                    news_daily=df_nw2.groupby([df_nw2["pubDate"].dt.date,"search_keyword"]).size().reset_index(name="뉴스 수")
                    news_daily.columns=["발행일","키워드","뉴스 수"]
                    st.plotly_chart(px.bar(news_daily,x="발행일",y="뉴스 수",color="키워드",barmode="group",title="날짜별 뉴스 발행 현황"),use_container_width=True)
                    from collections import Counter
                    all_nw_t=" ".join(df_nw2["title"].dropna().tolist())
                    stop_nw=[w for w in na_keywords]+["있는","이번","하는","그리고","이","가","을","는","에","의","도"]
                    nw_words=[w for w in all_nw_t.split() if len(w)>1 and w not in stop_nw]
                    nw_wc=Counter(nw_words).most_common(15)
                    if nw_wc:
                        df_nw_wc=pd.DataFrame(nw_wc,columns=["단어","빈도"])
                        fig_nw_wc=px.bar(df_nw_wc,x="빈도",y="단어",orientation="h",title="실시간 뉴스 핵심 키워드 (Hot Topics)",color="빈도",color_continuous_scale="Reds",text_auto=True)
                        fig_nw_wc.update_layout(yaxis={"categoryorder":"total ascending"})
                        st.plotly_chart(fig_nw_wc,use_container_width=True)
                    st.markdown("**☁️ 뉴스 이슈 워드클라우드**")
                    wc_nw=make_wordcloud(all_nw_t)
                    if wc_nw is not None: st.image(wc_nw,use_container_width=True,caption="News Word Cloud")
                    else: st.markdown(" ".join([f'`{w}({c})`' for w,c in Counter(nw_words).most_common(20)]))
                    st.divider()
                    st.markdown("**🗞️ 최신 뉴스 게시물**")
                    pg_nw=st.session_state.get("na_news_page",1)
                    sorted_nw=df_nw2.sort_values("pubDate",ascending=False)
                    total_nw=max(1,(len(sorted_nw)-1)//20+1); pg_nw=min(pg_nw,total_nw)
                    pn1,pn2,pn3=st.columns([1,3,1])
                    with pn1:
                        if st.button("이전",key="nw_prev",disabled=(pg_nw<=1)):
                            st.session_state["na_news_page"]=pg_nw-1; st.rerun()
                    with pn2: st.markdown(f"<div style='text-align:center;padding-top:.5rem'>{pg_nw}/{total_nw}</div>",unsafe_allow_html=True)
                    with pn3:
                        if st.button("다음",key="nw_next",disabled=(pg_nw>=total_nw)):
                            st.session_state["na_news_page"]=pg_nw+1; st.rerun()
                    st.dataframe(sorted_nw[["search_keyword","title","pubDate","link"]].iloc[(pg_nw-1)*20:pg_nw*20],
                        column_config={"search_keyword":st.column_config.TextColumn("키워드"),"title":st.column_config.TextColumn("제목",width="large"),"pubDate":st.column_config.DatetimeColumn("발행일시",format="YYYY-MM-DD HH:mm"),"link":st.column_config.LinkColumn("링크",display_text="바로가기")},
                        use_container_width=True,hide_index=True)
                    st.download_button("📥 뉴스 CSV",data=df_nw2.to_csv(index=False).encode("utf-8-sig"),file_name="news.csv",mime="text/csv")

            # ══ NST6: 쇼핑인사이트 ══════════════════════
            with nst6:
                st.markdown("#### 📊 쇼핑인사이트 — 카테고리 키워드 클릭 트렌드")
                st.caption(f"분석 기간: {na_start} ~ {na_end} | 키워드: {' | '.join(na_keywords)}")
                ins_c1,ins_c2=st.columns(2)
                with ins_c1:
                    ins_cat_name=st.selectbox("쇼핑 카테고리",list(INSIGHT_CATS.keys()) if INSIGHT_CATS else ["식품"],key="ins_cat")
                    ins_cat_id=INSIGHT_CATS.get(ins_cat_name,"50000006")
                with ins_c2:
                    ins_tu={"일별":"date","주별":"week","월별":"month"}[st.selectbox("집계 단위",["일별","주별","월별"],key="ins_tu")]

                if st.button("📊 쇼핑인사이트 분석",type="primary",use_container_width=True,key="ins_btn"):
                    with st.spinner(f"키워드 {len(na_keywords)}개 쇼핑인사이트 수집 중..."):
                        df_ins=naver_client.datalab_shopping_insight(ins_cat_id,na_keywords,na_start,na_end,ins_tu)
                    st.session_state["na_ins_df"]=df_ins

                df_ins=st.session_state.get("na_ins_df",pd.DataFrame())
                if not df_ins.empty:
                    df_ins["period"]=pd.to_datetime(df_ins["period"])
                    unique_kws=df_ins["keyword"].unique().tolist()
                    st.info(f"분석 키워드 {len(unique_kws)}개: {' | '.join(unique_kws)}")

                    # ① 키워드별 클릭 지수 추이
                    fig_ins=px.line(df_ins,x="period",y="ratio",color="keyword",
                                    title=f"키워드별 쇼핑 클릭 지수 추이 — {ins_cat_name}",markers=True,
                                    color_discrete_sequence=px.colors.qualitative.Vivid,
                                    labels={"period":"날짜","ratio":"클릭 지수(상대값)","keyword":"키워드"})
                    fig_ins.update_layout(hovermode="x unified",legend_title="키워드")
                    st.plotly_chart(fig_ins,use_container_width=True)
                    st.info("💡 클릭 지수는 기간 내 최대 수치를 100으로 둔 상대적 지표입니다.")

                    # ② 키워드별 상세 분석 + ③ 최고 인기 시점
                    sc1,sc2=st.columns(2)
                    with sc1:
                        st.markdown("**📈 키워드별 상세 분석**")
                        stats_ins=[]
                        for kw in unique_kws:
                            r=df_ins[df_ins["keyword"]==kw]["ratio"]
                            stats_ins.append({"키워드":kw,"평균 클릭지수":round(r.mean(),1),"최대 클릭지수":round(r.max(),1),"최소 클릭지수":round(r.min(),1),"변동성(표준편차)":round(r.std(),1)})
                        df_stats=pd.DataFrame(stats_ins)
                        st.dataframe(df_stats,use_container_width=True,hide_index=True)
                        fig_avg=px.bar(df_stats,x="키워드",y="평균 클릭지수",color="평균 클릭지수",title="키워드별 평균 클릭 지수 비교",text_auto=".1f",color_continuous_scale="Blues")
                        st.plotly_chart(fig_avg,use_container_width=True)
                    with sc2:
                        st.markdown("**🔥 키워드별 최고 인기 시점**")
                        peak_ins=[]
                        for kw in unique_kws:
                            kd=df_ins[df_ins["keyword"]==kw].sort_values("ratio",ascending=False)
                            peak_ins.append({"키워드":kw,"피크 날짜":kd.iloc[0]["period"].strftime("%Y-%m-%d"),"피크 지수":round(float(kd.iloc[0]["ratio"]),1)})
                        st.dataframe(pd.DataFrame(peak_ins),use_container_width=True,hide_index=True)

                        # ④ 최근 7일 vs 이전 7일
                        if len(df_ins)>=14:
                            st.markdown("**📊 최근 트렌드 변화 (최근 7일 vs 이전 7일)**")
                            ch_data=[]
                            for kw in unique_kws:
                                kd=df_ins[df_ins["keyword"]==kw].sort_values("period")
                                if len(kd)>=14:
                                    r7=kd.tail(7)["ratio"].mean()
                                    p7=kd.tail(14).head(7)["ratio"].mean()
                                    ch=round((r7-p7)/p7*100,1) if p7>0 else 0
                                    trend="📈 상승" if ch>5 else ("📉 하락" if ch<-5 else "➡️ 보합")
                                    ch_data.append({"키워드":kw,"최근7일":round(r7,1),"이전7일":round(p7,1),"변화율(%)":ch,"추세":trend})
                            if ch_data:
                                st.dataframe(pd.DataFrame(ch_data),use_container_width=True,hide_index=True)

                    st.download_button("📥 쇼핑인사이트 CSV",data=df_ins.to_csv(index=False).encode("utf-8-sig"),file_name=f"insight_{na_start}_{na_end}.csv",mime="text/csv")

                elif "na_ins_df" in st.session_state:
                    st.warning(f"카테고리 '{ins_cat_name}'에서 키워드 {na_keywords} 데이터가 없습니다.")
                    st.info("카테고리를 변경하거나 다른 키워드를 시도해보세요.")

            # ══ NST7: 종합 리포트 (dashboard.py 기반) ═══
            with nst7:
                st.markdown("#### 📑 마켓 인사이트 종합 리포트")
                st.info("💡 각 탭의 데이터를 취합하여 핵심 인사이트를 자동 요약합니다.")
                st.warning("⚠️ 본 리포트는 API 최대 100건 상위 노출 데이터 기반입니다. 전체 시장을 대변하지 않으므로 참고용으로 활용하세요.")

                # 데이터 수집 상태 확인
                df_t_r=st.session_state.get("na_trend_df",pd.DataFrame())
                df_s_r=st.session_state.get("na_shop_df",pd.DataFrame())
                df_bl_r=st.session_state.get("na_blog_df",pd.DataFrame())
                df_ca_r=st.session_state.get("na_cafe_df",pd.DataFrame())
                df_nw_r=st.session_state.get("na_news_df",pd.DataFrame())

                # ── KPI 스코어카드 ──────────────────────────
                trend_summary="데이터 부족"; avg_price=0; min_price=0; mall_count=0
                peak_date="-"; peak_kw="-"; trend_status="➡️"

                if not df_t_r.empty:
                    df_t_r2=df_t_r.copy(); df_t_r2["period"]=pd.to_datetime(df_t_r2["period"])
                    max_row=df_t_r2.sort_values("ratio",ascending=False).iloc[0]
                    peak_date=max_row["period"].strftime("%Y-%m-%d"); peak_kw=max_row["keyword"]
                    recent_avg=df_t_r2[df_t_r2["period"]>=df_t_r2["period"].max()-pd.Timedelta(days=3)]["ratio"].mean()
                    early_avg=df_t_r2[df_t_r2["period"]<=df_t_r2["period"].min()+pd.Timedelta(days=3)]["ratio"].mean()
                    if recent_avg>early_avg*1.1: trend_status="📈 상승세"
                    elif recent_avg<early_avg*0.9: trend_status="📉 하락세"
                    else: trend_status="➡️ 보합세"
                    trend_summary=f"{trend_status} (최고점: {peak_date}, {peak_kw})"

                if not df_s_r.empty:
                    df_s_r["lprice"]=pd.to_numeric(df_s_r["lprice"],errors="coerce")
                    avg_price=df_s_r["lprice"].mean(); min_price=df_s_r["lprice"].min()
                    mall_count=df_s_r["mall_name"].nunique()

                content_counts={"Blog":len(df_bl_r),"Cafe":len(df_ca_r),"News":len(df_nw_r)}
                total_content=sum(content_counts.values())
                top_channel=max(content_counts,key=content_counts.get) if total_content>0 else "-"

                r1,r2,r3,r4=st.columns(4)
                r1.metric("트렌드 상태",trend_status if trend_status!="➡️" else "데이터 없음")
                r2.metric("평균 시장가",f"{int(avg_price):,}원" if avg_price>0 else "-")
                r3.metric("총 콘텐츠 반응",f"{total_content:,}건")
                r4.metric("최다 활동 채널",top_channel)

                st.divider()
                rep1,rep2=st.columns([1,1])
                with rep1:
                    st.markdown("**📊 콘텐츠 채널별 점유율 (SOV)**")
                    if total_content>0:
                        df_sov=pd.DataFrame(list(content_counts.items()),columns=["채널","건수"])
                        fig_sov=px.pie(df_sov,values="건수",names="채널",hole=0.5,
                                       color_discrete_sequence=px.colors.qualitative.Pastel)
                        st.plotly_chart(fig_sov,use_container_width=True)
                    else:
                        st.info("블로그/카페/뉴스 탭에서 데이터를 먼저 수집하세요.")

                with rep2:
                    st.markdown("**📝 자동 생성 요약 리포트**")
                    kw_str=", ".join(na_keywords)
                    report=f"""### 1. 트렌드 분석
- 분석 기간 동안 검색 트렌드는 **{trend_summary}** 를 보이고 있습니다.
- 검색량이 가장 높았던 시점은 **{peak_date}** ({peak_kw}) 입니다.

### 2. 시장 가격 동향 (상위 100개 기준)
- 네이버 쇼핑 기준 평균 판매가는 **{int(avg_price):,}원** 입니다.
- 최저가는 **{int(min_price):,}원** 으로 형성되어 있습니다.
- 수집된 데이터 내 **{mall_count}** 개의 판매처가 확인됩니다.

### 3. 여론 및 콘텐츠 (최신 100건 기준)
- 수집된 **{total_content}** 건의 문서는 주로 **{top_channel}** 영역에서 생성되었습니다.
- 키워드: {kw_str}

> **Note**: 각 채널별 최대 100건 표본 기반 결과입니다."""
                    st.markdown(report)
                    st.download_button("📥 리포트 다운로드(TXT)",data=report,file_name=f"report_{datetime.now().strftime('%Y%m%d')}.txt",mime="text/plain")


with tab6:
    st.markdown("### 🛒 상품 자동 등록")
    st.info("관심 상품 탭에서 선별된 상품을 판매 플랫폼에 자동 등록합니다.")

    if not coupang_client:
        st.warning("쿠팡 자동 등록: COUPANG_ACCESS_KEY, COUPANG_SECRET_KEY, COUPANG_VENDOR_ID 필요")
        st.code("""COUPANG_ACCESS_KEY  = "쿠팡 Access Key"
COUPANG_SECRET_KEY  = "쿠팡 Secret Key (HmacSHA256 서명에 사용)"
COUPANG_VENDOR_ID   = "쿠팡 업체코드 A로 시작하는 문자열"
""",language="toml")
    else:
        tdf_reg=load_tracked()
        if tdf_reg.empty:
            st.info("관심 상품을 먼저 등록하세요.")
        else:
            tdf_reg_calc=apply_margin(tdf_reg,fee,mg)
            st.markdown("#### 등록할 상품 선택")
            selected_for_reg=st.multiselect(
                "등록할 상품",
                options=tdf_reg_calc["name"].tolist(),
                placeholder="등록할 상품을 선택하세요...")

            if selected_for_reg:
                reg_platform=st.selectbox("등록 플랫폼",["쿠팡"])
                reg_stock=st.number_input("재고 수량",min_value=1,value=10,step=1)
                reg_margin=st.slider("추가 마진 (%)",0,30,10,step=5)

                sel_prods=tdf_reg_calc[tdf_reg_calc["name"].isin(selected_for_reg)]
                st.dataframe(sel_prods[["name","supply_price","delivery_fee","추천 판매가(원)","마진율(%)"]].rename(
                    columns={"name":"상품명","supply_price":"공급가","delivery_fee":"배송비",
                             "추천 판매가(원)":"추천판매가","마진율(%)":"마진율"}),
                    use_container_width=True,hide_index=True)

                reg_ph=st.empty()
                if st.button(f"🛒 선택된 {len(selected_for_reg)}개 쿠팡 자동 등록",
                             type="primary",use_container_width=True):
                    success_cnt=0; fail_list=[]
                    prog=st.progress(0,"상품 등록 중...")
                    for i,(_,row) in enumerate(sel_prods.iterrows()):
                        prog.progress(i/len(sel_prods),f"{row['name'][:20]} 등록 중...")
                        sale_price=int(row["추천 판매가(원)"]*(1+reg_margin/100))
                        img_url=str(row.get("image_url","")).strip()
                        body=coupang_client.build_product_body(
                            name=row["name"],
                            category_code=50000000,
                            price=sale_price,
                            stock=reg_stock,
                            image_urls=[img_url] if img_url.startswith("http") else [],
                            brand=row.get("site",""),
                        )
                        result=coupang_client.create_product(body)
                        if result.get("code")=="SUCCESS":
                            success_cnt+=1
                        else:
                            fail_list.append(row["name"][:20])
                        _time.sleep(1)
                    prog.progress(1.0,"완료!")
                    if success_cnt>0: reg_ph.success(f"✅ {success_cnt}개 등록 완료")
                    if fail_list: reg_ph.warning(f"⚠️ 실패: {', '.join(fail_list[:3])}")

    st.markdown("---")
    st.markdown("#### 네이버 스마트스토어 자동 등록")
    st.warning("네이버 스마트스토어 커머스 API는 별도 사업자 심사가 필요합니다.")
    st.markdown("""
승인 신청 방법:
1. sell.smartstore.naver.com 로그인
2. 판매자 정보 → API 이용 신청
3. 사업자 등록증 업로드 후 심사 (1~3영업일)
4. 승인 후 CLIENT_ID, CLIENT_SECRET 발급
5. Secrets에 NAVER_COMMERCE_CLIENT_ID, NAVER_COMMERCE_CLIENT_SECRET 등록
    """)

# ══════════════════════════════════════════════════════════════
# TAB 7 — 주문/송장 관리
# ══════════════════════════════════════════════════════════════
with tab7:
    st.markdown("### 📦 주문/송장 관리")

    if not coupang_client:
        st.warning("쿠팡 API 키를 Secrets에 등록하세요.")
    else:
        order_tab1,order_tab2,order_tab3=st.tabs(["📋 발주서 조회","🚚 송장 업로드","📊 정산 조회"])

        with order_tab1:
            st.markdown("#### 발주서 조회")
            oc1,oc2,oc3=st.columns(3)
            with oc1: order_status=st.selectbox("주문 상태",["ACCEPT","DEPARTURE","DELIVERING","DELIVERED"])
            with oc2: order_date=st.date_input("조회 날짜",value=datetime.now())
            with oc3: st.write("")
            _ord_ph=st.empty()
            if st.button("📋 발주서 조회",type="primary",use_container_width=True):
                with st.spinner("발주서 조회 중..."):
                    orders=coupang_client.get_orders(status=order_status,
                                                     date=order_date.strftime("%Y-%m-%d"))
                if orders:
                    st.success(f"{len(orders)}건 조회됨")
                    df_ord=pd.DataFrame(orders)
                    st.dataframe(df_ord,use_container_width=True,hide_index=True)
                    if sheets_manager:
                        if st.button("📊 구글 시트에 기록",use_container_width=True):
                            ok=sheets_manager.log_orders(orders)
                            if ok: _ord_ph.success("✅ 시트 기록 완료")
                            else: _ord_ph.error("❌ 시트 기록 실패")
                else:
                    st.info("조회된 발주서 없음")

        with order_tab2:
            st.markdown("#### 송장 일괄 업로드")
            st.caption("CSV 파일로 송장을 일괄 업로드합니다. (주문번호, 송장번호, 택배사코드)")
            uploaded_csv=st.file_uploader("송장 CSV 업로드",type=["csv"])
            courier_options={"CJ대한통운":"CJ","한진택배":"HANJIN","롯데택배":"LOTTE",
                             "우체국택배":"POST","로젠택배":"KGB"}
            default_courier=st.selectbox("기본 택배사",list(courier_options.keys()))
            trk_ph=st.empty()
            if uploaded_csv:
                try:
                    df_csv=pd.read_csv(uploaded_csv)
                    st.dataframe(df_csv.head(10),use_container_width=True,hide_index=True)
                    if st.button("🚚 송장 일괄 업로드",type="primary",use_container_width=True):
                        success_cnt=0; fail_cnt=0
                        prog=st.progress(0,"송장 업로드 중...")
                        for i,row in df_csv.iterrows():
                            prog.progress(i/len(df_csv))
                            order_id=str(row.get("주문번호",row.get("order_id","")))
                            tracking=str(row.get("송장번호",row.get("tracking_number","")))
                            courier=courier_options.get(
                                str(row.get("택배사",default_courier)),
                                courier_options[default_courier])
                            if order_id and tracking:
                                result=coupang_client.upload_tracking(order_id,tracking,courier)
                                if result.get("code")=="SUCCESS": success_cnt+=1
                                else: fail_cnt+=1
                            _time.sleep(0.5)
                        prog.progress(1.0,"완료!")
                        trk_ph.success(f"✅ 성공 {success_cnt}건 / 실패 {fail_cnt}건")
                except Exception as e:
                    st.error(f"CSV 파싱 오류: {e}")

            st.markdown("**CSV 형식 예시:**")
            st.code("주문번호,송장번호,택배사\n1234567890,123456789012,CJ대한통운",language="text")

        with order_tab3:
            st.markdown("#### 정산 조회")
            sc1,sc2=st.columns(2)
            with sc1: settle_start=st.date_input("시작일")
            with sc2: settle_end=st.date_input("종료일")
            _set_ph=st.empty()
            if st.button("📊 정산 조회",use_container_width=True):
                with st.spinner("정산 조회 중..."):
                    settlements=coupang_client.get_settlements(
                        settle_start.strftime("%Y-%m-%d"),
                        settle_end.strftime("%Y-%m-%d"))
                if settlements:
                    df_set=pd.DataFrame(settlements)
                    st.dataframe(df_set,use_container_width=True,hide_index=True)
                    if sheets_manager:
                        if st.button("📊 구글 시트 기록",use_container_width=True,key="set_sh"):
                            ok=sheets_manager.log_settlement(settlements)
                            if ok: _set_ph.success("✅ 기록 완료")
                else:
                    st.info("정산 내역 없음")

# ══════════════════════════════════════════════════════════════
# TAB 8 — 텔레그램
# ══════════════════════════════════════════════════════════════
with tab8:
    st.markdown("### 📱 텔레그램 설정")
    ca,cb=st.columns(2)
    with ca:
        st.markdown("""
봇 만들기: @BotFather → /newbot → 토큰 복사
채팅방 ID: api.telegram.org/bot[토큰]/getUpdates
다중 수신자: TELEGRAM_CHAT_IDS에 콤마로 여러 ID 입력
        """)
    with cb:
        st.code("""DOMEGGOOK_API_KEY  = "API키"
TELEGRAM_BOT_TOKEN = "봇토큰"
TELEGRAM_CHAT_IDS  = "내ID,친구ID"
GEMINI_API_KEY     = "제미나이키(무료)"
NAVER_CLIENT_ID    = "네이버 Client ID"
NAVER_CLIENT_SECRET= "네이버 Client Secret"
COUPANG_ACCESS_KEY = "쿠팡 Access Key"
COUPANG_SECRET_KEY = "쿠팡 Secret Key"
COUPANG_VENDOR_ID  = "쿠팡 업체코드"
GOOGLE_SERVICE_ACCOUNT_JSON = '''서비스계정 JSON 전체'''
GOOGLE_SHEET_ID    = "구글 시트 ID"
""",language="toml")
        _t8ph=st.empty()
        tm2=st.text_input("테스트 메시지",value="소싱레이더 v9.0 연동 테스트")
        if st.button("테스트 발송",type="primary",use_container_width=True):
            ok=send_telegram_message(tm2)
            if ok: _t8ph.success("✅ 성공")
            else: _t8ph.error("❌ 실패")

# ══════════════════════════════════════════════════════════════
# TAB 9 — 가이드
# ══════════════════════════════════════════════════════════════
with tab9:
    st.markdown("### 📖 가이드")
    with st.expander("API 키 발급 방법"):
        st.markdown("""
네이버 API (무료)
1. developers.naver.com 로그인
2. 애플리케이션 등록 → 검색 API, 데이터랩 API 추가
3. Client ID, Client Secret 발급

쿠팡 Open API
1. Wing 로그인 (seller.coupang.com)
2. 우측 상단 업체명 → 업체정보 → Open API 키 발급
3. Access Key, Secret Key, 업체코드(A...) 확인

Google Sheets
1. console.cloud.google.com → 서비스 계정 생성
2. JSON 키 다운로드
3. 구글 시트 공유 → 서비스 계정 이메일 편집자 권한
4. Secrets에 JSON 전체 내용과 시트 ID 등록
        """)
    with st.expander("도매매/도매꾹 링크 안내"):
        st.markdown("""
도매매와 도매꾹은 동일 회사(domeggook.com)의 두 채널입니다.
카드에 '도매매'로 표시되어도 클릭 시 domeggook.com으로 이동하는 것이 정상입니다.
도매매 상품은 URL에 &market=supply 파라미터로 구분됩니다.
        """)
    with st.expander("AI 이미지 생성 사용법"):
        st.markdown("""
1. 브랜드명, 카테고리, 특징 입력
2. 상품 이미지 업로드 (선택 — 패키지 정보 반영)
3. 체크박스 리스트에서 생성할 이미지 선택 (1~4개 권장)
4. 생성 버튼 클릭
5. DALL-E 3 Prompt 복사 → ChatGPT(GPT-4o) 붙여넣기

Gemini 무료 한도: 분당 15회 → 이미지 사이 4초 자동 대기
ChatGPT 무료: 하루 일정 횟수 / Plus $20월: 무제한
        """)
    with st.expander("수수료 및 마진 계산"):
        st.markdown("""
| 플랫폼 | 수수료 |
|---|---|
| 네이버 스마트스토어 | 6% |
| 쿠팡 | 11% |
| 11번가 | 12% |
| G마켓 | 12% |
| 옥션 | 12% |

추천 판매가 = (공급가 + 배송비) ÷ (1 - 수수료율 - 목표마진율)
        """)

# ══════════════════════════════════════════════════════════════
# TAB 10 — 종합 리포트 (시장 분석 데이터 기반)
# ══════════════════════════════════════════════════════════════
with tab10:
    st.markdown("### 📑 마켓 인사이트 종합 리포트")
    st.info("💡 시장 분석 탭에서 수집된 데이터를 기반으로 자동 생성됩니다. 먼저 시장 분석 탭에서 키워드를 입력하고 각 탭 데이터를 수집하세요.")
    st.warning("⚠️ 본 리포트는 API 최대 100건 상위 노출 데이터 기반입니다. 참고용으로만 활용하세요.")

    df_t_r=st.session_state.get("na_trend_df",pd.DataFrame())
    df_s_r=st.session_state.get("na_shop_df",pd.DataFrame())
    df_bl_r=st.session_state.get("na_blog_df",pd.DataFrame())
    df_ca_r=st.session_state.get("na_cafe_df",pd.DataFrame())
    df_nw_r=st.session_state.get("na_news_df",pd.DataFrame())
    na_kw_r=st.session_state.get("na_prev_kw",["키워드 없음"])

    trend_summary="데이터 없음"; avg_price=0; min_price=0; mall_count=0
    peak_date="-"; peak_kw="-"; trend_status="데이터 없음"
    if not df_t_r.empty:
        df_t_r2=df_t_r.copy(); df_t_r2["period"]=pd.to_datetime(df_t_r2["period"])
        max_row=df_t_r2.sort_values("ratio",ascending=False).iloc[0]
        peak_date=max_row["period"].strftime("%Y-%m-%d"); peak_kw=max_row["keyword"]
        recent_avg=df_t_r2[df_t_r2["period"]>=df_t_r2["period"].max()-pd.Timedelta(days=3)]["ratio"].mean()
        early_avg=df_t_r2[df_t_r2["period"]<=df_t_r2["period"].min()+pd.Timedelta(days=3)]["ratio"].mean()
        if recent_avg>early_avg*1.1: trend_status="📈 상승세"
        elif recent_avg<early_avg*0.9: trend_status="📉 하락세"
        else: trend_status="➡️ 보합세"
        trend_summary=f"{trend_status} (최고점: {peak_date}, {peak_kw})"
    if not df_s_r.empty:
        df_s_r["lprice"]=pd.to_numeric(df_s_r["lprice"],errors="coerce")
        avg_price=df_s_r["lprice"].mean(); min_price=df_s_r["lprice"].min()
        mall_count=df_s_r["mall_name"].nunique()
    content_counts={"Blog":len(df_bl_r),"Cafe":len(df_ca_r),"News":len(df_nw_r)}
    total_content=sum(content_counts.values())
    top_channel=max(content_counts,key=content_counts.get) if total_content>0 else "-"

    r1,r2,r3,r4=st.columns(4)
    r1.metric("트렌드 상태",trend_status)
    r2.metric("평균 시장가",f"{int(avg_price):,}원" if avg_price>0 else "-")
    r3.metric("총 콘텐츠 반응",f"{total_content:,}건")
    r4.metric("최다 활동 채널",top_channel)
    st.divider()
    rep1,rep2=st.columns([1,1])
    with rep1:
        st.markdown("**📊 콘텐츠 채널별 점유율 (SOV)**")
        if total_content>0:
            df_sov=pd.DataFrame(list(content_counts.items()),columns=["채널","건수"])
            st.plotly_chart(px.pie(df_sov,values="건수",names="채널",hole=0.5,color_discrete_sequence=px.colors.qualitative.Pastel),use_container_width=True)
        else:
            st.info("시장 분석 탭에서 데이터를 먼저 수집하세요.")
    with rep2:
        st.markdown("**📝 자동 생성 요약 리포트**")
        kw_str=", ".join(na_kw_r)
        report=f"""### 1. 트렌드 분석
- 분석 기간 동안 검색 트렌드는 **{trend_summary}** 를 보이고 있습니다.
- 검색량이 가장 높았던 시점은 **{peak_date}** ({peak_kw}) 입니다.

### 2. 시장 가격 동향 (상위 100개 기준)
- 네이버 쇼핑 기준 평균 판매가는 **{int(avg_price):,}원** 입니다.
- 최저가는 **{int(min_price):,}원** 으로 형성되어 있습니다.
- 수집된 데이터 내 **{mall_count}** 개의 판매처가 확인됩니다.

### 3. 여론 및 콘텐츠 (최신 100건 기준)
- 수집된 **{total_content}** 건의 문서는 주로 **{top_channel}** 영역에서 생성되었습니다.
- 분석 키워드: {kw_str}

> Note: 각 채널별 최대 100건 표본 기반 결과입니다."""
        st.markdown(report)
        st.download_button("📥 리포트 다운로드(TXT)",data=report,file_name=f"report_{datetime.now().strftime('%Y%m%d')}.txt",mime="text/plain")
