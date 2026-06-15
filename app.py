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
from datetime import datetime
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
    except: pass

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
        "CRITICAL: The top 38% of the vertical canvas must be a completely flat, solid, "
        "single-tone color with zero textures, objects, patterns or gradients — "
        "reserved strictly for Korean text overlay in post-production. "
        "Product occupies lower 62% of frame. "
        "Professional studio lighting, mobile-first single focal point, high contrast. "
        f"Target customer: {target if target else 'Korean adults 20-50'}. "
        "No text, no watermarks, no fake ratings. "
        f"Aspect ratio 860x{spec['h']} pixels (tall vertical format)."
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
        "DALL-E 3 Prompt (아래 내용 전체를 ChatGPT에 붙여넣기):\n\n"
        "이 프롬프트로 이미지를 생성해줘:\n\n"
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

tab1,tab2,tab3,tab4,tab5,tab6,tab7,tab8,tab9=st.tabs([
    "🔍 라이브 검색","⭐ 관심 상품","🔑 키워드 생성","🎨 AI 이미지 생성",
    "📊 시장 분석","🛒 상품 등록","📦 주문/송장","📱 텔레그램","📖 가이드"])

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
            iup=st.file_uploader("상품 이미지 업로드 (선택 — 패키지 정보 반영)",
                                 type=["jpg","jpeg","png","webp"],key="iup")
            if iup:
                st.image(iup,width=180,caption="업로드 이미지")
                st.caption("Gemini Vision이 패키지 색상·형태를 분석해 DALL-E 3 프롬프트에 반영합니다.")
        iff=st.text_area("상품 주요 특징 *",placeholder="1. 특징1\n2. 특징2\n3. 특징3",height=100,key="iff")

    # ★ 이미지 전체 체크박스 리스트 UI
    st.markdown("#### 생성할 이미지 선택")
    st.caption("전체 선택/해제 후 원하는 항목만 체크하세요. Gemini 무료 한도를 위해 1~4개씩 권장합니다.")

    col_sel, col_desel = st.columns([1,1])
    with col_sel:
        if st.button("☑️ 전체 선택",use_container_width=True):
            st.session_state["img_checked"]=list(range(1,13)); st.rerun()
    with col_desel:
        if st.button("☐ 전체 해제",use_container_width=True):
            st.session_state["img_checked"]=[]; st.rerun()

    checked=st.session_state.get("img_checked",list(range(1,13)))
    new_checked=[]
    cols_chk=st.columns(2)
    for i,spec in enumerate(IMAGE_SPEC):
        with cols_chk[i%2]:
            is_chk=spec["no"] in checked
            val=st.checkbox(
                f"**{spec['no']:02d}** — {spec['stage']} ({spec['kr']})  |  860×{spec['h']}px  |  {spec['desc']}",
                value=is_chk, key=f"img_chk_{spec['no']}")
            if val: new_checked.append(spec["no"])
    st.session_state["img_checked"]=new_checked

    sel_count=len(new_checked)
    if sel_count>0:
        st.info(f"✅ {sel_count}개 선택됨 — 예상 소요 시간: 약 {sel_count*15}~{sel_count*25}초")

    if st.button(f"🎨 선택된 {sel_count}개 이미지 프롬프트 생성",type="primary",
                 use_container_width=True,
                 disabled=(not GEMINI_KEY or not ib or not iff or sel_count==0)):
        sel_specs=[s for s in IMAGE_SPEC if s["no"] in new_checked]
        image_b64=""
        if iup:
            try: image_b64=base64.b64encode(iup.getvalue()).decode("utf-8")
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
# TAB 5 — 시장 분석 (네이버 데이터랩 + 쿠팡)
# ══════════════════════════════════════════════════════════════
with tab5:
    st.markdown("### 📊 시장 분석")
    if not naver_client and not coupang_client:
        st.warning("네이버 API 또는 쿠팡 API 키를 Secrets에 등록하세요.")
        st.code("""# Streamlit Secrets 등록
NAVER_CLIENT_ID     = "네이버 Client ID"
NAVER_CLIENT_SECRET = "네이버 Client Secret"
COUPANG_ACCESS_KEY  = "쿠팡 Access Key"
COUPANG_SECRET_KEY  = "쿠팡 Secret Key"
COUPANG_VENDOR_ID   = "쿠팡 업체코드 (A로 시작)"
""", language="toml")
        st.info("네이버 API 발급: developers.naver.com → 애플리케이션 등록\n쿠팡 API 발급: Wing 로그인 → 업체정보 → Open API 키 발급")
    else:
        analysis_tab1,analysis_tab2=st.tabs(["🔍 네이버 시장 분석","🛒 쿠팡 시장 분석"])

        with analysis_tab1:
            if not naver_client:
                st.warning("NAVER_CLIENT_ID, NAVER_CLIENT_SECRET을 Secrets에 등록하세요.")
            else:
                st.markdown("#### 네이버 쇼핑 검색 + 데이터랩")
                na_kw=st.text_input("분석할 키워드",placeholder="예: 냉동딸기, 텀블러",key="na_kw")
                na_col1,na_col2=st.columns(2)
                with na_col1: na_type=st.selectbox("검색 유형",["쇼핑","블로그","뉴스"])
                with na_col2: na_period=st.selectbox("트렌드 기간",["1개월","3개월","6개월"])
                period_map={"1개월":1,"3개월":3,"6개월":6}

                if st.button("📊 분석 시작",type="primary",use_container_width=True,disabled=(not na_kw)):
                    with st.spinner("네이버 데이터 수집 중..."):
                        if na_type=="쇼핑":
                            results=naver_client.search_shopping(na_kw,display=20)
                            if results:
                                df_nv=pd.DataFrame(results)
                                st.markdown(f"**쇼핑 검색 결과 ({len(results)}개)**")
                                st.dataframe(df_nv[["title","mall_name","lprice","hprice","category1","category2"]].rename(
                                    columns={"title":"상품명","mall_name":"쇼핑몰","lprice":"최저가","hprice":"최고가","category1":"대분류","category2":"중분류"}),
                                    use_container_width=True,hide_index=True)
                                if df_nv["lprice"].sum()>0:
                                    avg_price=int(df_nv[df_nv["lprice"]>0]["lprice"].mean())
                                    min_price=int(df_nv["lprice"].min())
                                    st.metric("평균 최저가",f"{avg_price:,}원",f"최저 {min_price:,}원")
                        elif na_type=="블로그":
                            results=naver_client.search_blog(na_kw)
                            for r in results[:5]:
                                st.markdown(f"**[{r['title']}]({r['link']})**\n{r['description'][:100]}...\n{r['postdate']}")
                        else:
                            results=naver_client.search_news(na_kw)
                            for r in results[:5]:
                                st.markdown(f"**[{r['title']}]({r['link']})**\n{r['description'][:100]}...\n{r['pubDate']}")

                        # 데이터랩 트렌드
                        st.markdown("**📈 검색어 트렌드 (데이터랩)**")
                        trend=naver_client.datalab_trend([na_kw],period_months=period_map[na_period])
                        results_t=trend.get("results",[])
                        if results_t:
                            data_pts=results_t[0].get("data",[])
                            if data_pts:
                                df_trend=pd.DataFrame(data_pts)
                                df_trend.columns=["날짜","검색량(상대값)"]
                                st.line_chart(df_trend.set_index("날짜"))
                        else:
                            st.info("트렌드 데이터를 가져오지 못했습니다.")

        with analysis_tab2:
            if not coupang_client:
                st.warning("COUPANG_ACCESS_KEY, COUPANG_SECRET_KEY, COUPANG_VENDOR_ID를 Secrets에 등록하세요.")
            else:
                st.markdown("#### 쿠팡 상품 조회")
                st.info("쿠팡 Open API는 자사 등록 상품 조회 및 주문 관리 기능을 제공합니다.")
                if st.button("📦 오늘 신규 주문 확인",use_container_width=True):
                    with st.spinner("쿠팡 발주서 조회 중..."):
                        orders=coupang_client.get_orders(status="ACCEPT")
                    if orders:
                        df_ord=pd.DataFrame(orders)
                        st.success(f"신규 주문 {len(orders)}건")
                        st.dataframe(df_ord,use_container_width=True,hide_index=True)
                    else:
                        st.info("신규 주문 없음")

# ══════════════════════════════════════════════════════════════
# TAB 6 — 상품 자동 등록
# ══════════════════════════════════════════════════════════════
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
