"""
소싱레이더 v8.1 — Final Release
- 온채널 완전 제거
- 업체등급 디버그 강화 (로그에 seller 원문 출력)
- AI 이미지: 상품 이미지 업로드 방식 (URL 이미지 참조 제거)
- 키워드: 네이버/쿠팡 실시간 자동완성 기반 생성
- 텔레그램 다중 수신자 (TELEGRAM_CHAT_IDS)
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
.kl{font-size:.72rem;color:#64748b;font-weight:600;text-transform:uppercase;
    letter-spacing:.05em;margin-bottom:.3rem}
.kv{font-size:1.7rem;font-weight:700;color:#1e293b;line-height:1}
.ks{font-size:.72rem;color:#94a3b8;margin-top:.2rem}
section[data-testid="stSidebar"]{background:#1a1a2e !important}
section[data-testid="stSidebar"] *{color:#cbd5e1 !important}
.stButton>button{border-radius:8px !important;font-weight:600 !important}
.stTabs [data-baseweb="tab-list"]{gap:4px;background:#f1f5f9;border-radius:10px;padding:4px}
.stTabs [data-baseweb="tab"]{border-radius:8px !important;font-weight:500 !important}
.stTabs [aria-selected="true"]{background:white !important;box-shadow:0 1px 3px rgba(0,0,0,.1) !important}
.kw-chip{display:inline-block;background:#EFF6FF;color:#1D4ED8;font-size:.78rem;
    padding:3px 10px;border-radius:20px;margin:2px;font-weight:500}
footer{visibility:hidden}
</style>""", unsafe_allow_html=True)

# ── Secrets ──────────────────────────────────────────────────
try:
    DOME_KEY   = st.secrets["DOMEGGOOK_API_KEY"]
    GEMINI_KEY = st.secrets.get("GEMINI_API_KEY","")
except Exception:
    DOME_KEY = GEMINI_KEY = ""

init_db()
client = DomeameClient(api_key=DOME_KEY) if DOME_KEY else None

CATEGORY_MAP={
    "전체보기":{"전체보기":"0000"},
    "패션의류":{"전체보기":"01","여성의류":"0101","남성의류":"0102","언더웨어":"0103"},
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
    {"no":1,"stage":"HOOK","kr":"훅","h":2200},
    {"no":2,"stage":"Painpoint","kr":"문제 공감","h":1800},
    {"no":3,"stage":"Solution","kr":"해결 제안","h":2000},
    {"no":4,"stage":"USP1","kr":"핵심 가치 1","h":1800},
    {"no":5,"stage":"USP2","kr":"핵심 가치 2","h":1800},
    {"no":6,"stage":"USP3","kr":"핵심 가치 3","h":1800},
    {"no":7,"stage":"USP4","kr":"핵심 가치 4","h":1800},
    {"no":8,"stage":"TPO","kr":"활용성","h":1800},
    {"no":9,"stage":"Certification","kr":"신뢰","h":2500},
    {"no":10,"stage":"SpecsInfo","kr":"상세 정보","h":2800},
    {"no":11,"stage":"Audience","kr":"추천 대상","h":1600},
    {"no":12,"stage":"CTA","kr":"행동 유도","h":1800},
]

for k,v in {"live_results":[],"show_results":False,"search_error":None,"page_num":0,
            "ai_result":None,"live_view":"card","mon_view":"card",
            "kw_result":None,"img_prompts":{},"card_ai_selected":set(),"grade_cache":{}}.items():
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
    except Exception as e: st.error(f"DB: {e}"); return pd.DataFrame()

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
    st.session_state.update({"search_kw":"","live_results":[],"show_results":False,"search_error":None,"page_num":0,"ai_result":None,"card_ai_selected":set()})
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

def gc(grade):
    g=grade[0].upper() if grade and grade[0].isalpha() else ""
    return {"S":"#f59e0b","A":"#3b82f6","B":"#22c55e","C":"#eab308","D":"#f97316","E":"#ef4444"}.get(g,"#94a3b8")

def copy_btn(text:str, label:str="📋 복사")->str:
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
                is_t=pid in tracked_ids; url=prod_url(row); color=gc(grade)
                if img and img.startswith("http"):
                    link=f'<a href="{url}" target="_blank">' if url else ""
                    close="</a>" if url else ""
                    st.markdown(f'{link}<img src="{img}" style="width:100%;border-radius:8px;margin-bottom:6px"/>{close}',unsafe_allow_html=True)
                else:
                    a=f'href="{url}" target="_blank"' if url else ""
                    st.markdown(f'<a {a}><div style="height:90px;background:#f1f5f9;border-radius:8px;display:flex;align-items:center;justify-content:center;font-size:2.5rem;margin-bottom:6px">📦</div></a>',unsafe_allow_html=True)
                name_part=(f'<a href="{url}" target="_blank" style="color:#1e293b;text-decoration:none">{row["name"][:30]}</a>' if url else row["name"][:30])
                grade_part=(f'<span style="background:{color}22;color:{color};padding:2px 8px;border-radius:6px;font-size:.75rem;font-weight:600">{grade}</span>'
                            if grade else '<span style="color:#94a3b8;font-size:.72rem">미조회</span>')
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
                lbl="⭐ 등록됨" if is_t else "☆ 관심 등록"
                if st.button(lbl,key=f"{pfx}_c_{pid}",use_container_width=True):
                    on_toggle(row.to_dict(),0 if is_t else 1); st.rerun()

def tg_long(text,prefix="📡 소싱레이더"):
    chunks=[text[i:i+3800] for i in range(0,len(text),3800)]
    ok=True
    for i,c in enumerate(chunks):
        hdr=prefix if len(chunks)==1 else f"{prefix} ({i+1}/{len(chunks)})"
        if not send_telegram_message(f"{hdr}\n\n{c}"): ok=False
        if i<len(chunks)-1: _time.sleep(0.5)
    return ok

def gemini(prompt,max_tok=1500,retries=3):
    if not GEMINI_KEY: return "GEMINI_API_KEY 미설정"
    for attempt in range(retries):
        try:
            r=req.post(
                f"https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash-lite:generateContent?key={GEMINI_KEY}",
                headers={"Content-Type":"application/json"},
                json={"contents":[{"parts":[{"text":prompt}]}],"generationConfig":{"maxOutputTokens":max_tok,"temperature":0.15}},
                timeout=90)
            if r.status_code==200: return r.json()["candidates"][0]["content"]["parts"][0]["text"]
            if r.status_code==429:
                wait=15*(attempt+1); print(f"[429] {wait}초 대기"); _time.sleep(wait); continue
            return f"Gemini 오류 {r.status_code}: {r.text[:200]}"
        except Exception as e:
            if attempt<retries-1: _time.sleep(10); continue
            return f"AI 오류: {e}"
    return "Gemini 429 — 1분 후 재시도하세요"

def gemini_vision(prompt,image_b64,max_tok=1000):
    """이미지 포함 Gemini 호출"""
    if not GEMINI_KEY: return "GEMINI_API_KEY 미설정"
    try:
        r=req.post(
            f"https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash:generateContent?key={GEMINI_KEY}",
            headers={"Content-Type":"application/json"},
            json={"contents":[{"parts":[
                {"text":prompt},
                {"inline_data":{"mime_type":"image/jpeg","data":image_b64}}
            ]}],"generationConfig":{"maxOutputTokens":max_tok,"temperature":0.15}},
            timeout=60)
        if r.status_code==200: return r.json()["candidates"][0]["content"]["parts"][0]["text"]
        if r.status_code==429: _time.sleep(30); return gemini(prompt,max_tok)  # Vision 실패시 텍스트로 fallback
        return f"Vision 오류 {r.status_code}"
    except Exception as e: return gemini(prompt,max_tok)

def compact_ai(df,fee,mg,pname,mname):
    rows=[]
    for _,r in df.iterrows():
        rows.append(f"{r['name'][:28]}({r.get('site','')})\n"
                    f"  원가{int(r.get('supply_price',0))+int(r.get('delivery_fee',0)):,}원 "
                    f"판매가{int(r.get('추천 판매가(원)',0)):,}원 "
                    f"순수익{int(r.get('예상 순수익(원)',0)):,}원/건 "
                    f"마진{r.get('마진율(%)',0):.1f}% 등급{r.get('seller_grade','미확인') or '미확인'}")
    prompt=f"""이커머스 소싱 전문가. 핵심만 간결하게.
판매: {pname} 수수료{int(fee*100)}% / 목표마진{int(mg*100)}%
{chr(10).join(rows)}

형식 (이모티콘 유지, 줄 앞 -, #, * 금지):
🏆 즉시 소싱 TOP3
1 상품명 이유
2 상품명 이유
3 상품명 이유

❌ 제외 권장
상품명 이유

📊 개별 판정
상품명 ✅/👍/⚠️/❌ 마진(상중하) 리스크 월50건수익원

💡 이번달 전략
1 액션
2 액션
3 액션

⚠️ 주의 2줄"""
    return gemini(prompt,1500)

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
    if naver: realtime+=f"\n네이버 쇼핑 인기 검색어: {', '.join(naver)}"
    if coupang: realtime+=f"\n쿠팡 인기 검색어: {', '.join(coupang)}"
    if not realtime: realtime="\n(실시간 수집 불가 — AI 분석으로 대체)"

    guides={"네이버 스마트스토어":"브랜드+상품유형+특징+타겟, 최대100자, 키워드10개",
            "쿠팡":"핵심상품명+용량+특징, 최대50자, 키워드8개",
            "11번가":"브랜드+상품명+규격+수량, 최대80자, 키워드10개",
            "G마켓":"브랜드+유형+특징+구성, 최대80자, 키워드10개",
            "옥션":"브랜드+유형+수량+혜택, 최대80자, 키워드10개"}

    prompt=f"""이커머스 SEO 전문가. 플랫폼별 최적 키워드 생성.

상품명: {prod}
특징: {feat}
실시간 인기 검색어:{realtime}

{chr(10).join([f"[{p}] {guides.get(p,'')}" for p in platforms])}

출력 형식 (## 없이, 플랫폼별 --- 구분):

[플랫폼명]
추천 상품명: (최적 상품명)
핵심 키워드: 키워드1, 키워드2, 키워드3, 키워드4, 키워드5
롱테일 키워드: 롱테일1, 롱테일2, 롱테일3
태그: 태그1, 태그2, 태그3, 태그4, 태그5
실시간 트렌드: (위 인기 검색어 중 적합한 것)
등록 팁: 한줄

---"""
    return gemini(prompt,2000)

def gen_img_prompt(spec,brand,features,target,category,image_b64=""):
    """이미지 1개 DALL-E 3 프롬프트 생성 (품질 개선판 v9.1)"""
    pkg_desc = ""
    if image_b64:
        vq = ("Analyze this product image in English (3-4 sentences): "
              "1. Packaging shape/size 2. Color palette 3. Label design style "
              "4. Material texture. Brand: " + brand)
        pkg_analysis = gemini_vision(vq, image_b64, max_tok=250)
        if "오류" not in pkg_analysis and "Error" not in pkg_analysis:
            pkg_desc = "\nProduct Visual (from uploaded image):\n" + pkg_analysis

    stage_dir = {
        "HOOK":"Hero product shot, 3-second attention grab, premium lifestyle",
        "Painpoint":"Customer frustration scene, emotional empathy, no product",
        "Solution":"Product as dramatic solution, bright color shift",
        "USP1":"Close-up of key feature, sharp detail focus",
        "USP2":"Functional benefit in realistic use",
        "USP3":"Ingredient/material macro, scientific precision",
        "USP4":"Lifestyle convenience, portability, emotional satisfaction",
        "TPO":"Multiple daily-life scenes (morning/office/outdoor)",
        "Certification":"Quality seal visual, clean manufacturing background",
        "SpecsInfo":"Product spec info-graphic, clean table layout",
        "Audience":"Icon-based target persona matching chart",
        "CTA":"Full product bundle, premium hero, purchase motivation"
    }.get(spec["stage"], "Premium commercial product photography")

    dalle_q = (
        "You are a senior Naver Smartstore visual designer. "
        "Write a complete DALL-E 3 image prompt (minimum 120 words, English only).\n\n"
        "PRODUCT: " + brand + " (" + category + ")\n"
        "TARGET: " + (target if target else "Korean adults 20-50") + "\n"
        "FEATURES: " + features
        + pkg_desc +
        "\nIMAGE #" + str(spec["no"]) + ": " + spec["stage"] + " (" + spec["kr"] + ") | 860x" + str(spec["h"]) + "px"
        "\nSTAGE DIRECTION: " + stage_dir +
        "\n\nMANDATORY:\n"
        "- Top 38% = FLAT SOLID single-color background (zero objects, for text overlay)\n"
        "- NO text in image\n"
        "- Photorealistic commercial photography\n"
        "- Single focal point, mobile-first\n"
        "- NO fake reviews/certifications\n\n"
        "Write ONLY the prompt starting with 'Photorealistic':"
    )
    dalle_result = gemini(dalle_q, max_tok=1200)

    copy_q = (
        "스마트스토어 상세페이지 " + str(spec["no"]) + "번(" + spec["kr"] + ") 광고 카피:\n"
        "상품: " + brand + " (" + category + ")\n"
        "특징: " + features[:200] + "\n\n"
        "메인 카피: (15-25자, 숫자 포함)\n"
        "서브 카피: (1-2문장)\n"
        "전환 포인트: (구매 유도 요소)"
    )
    copy_result = gemini(copy_q, max_tok=300)

    final = (
        "[Image " + f"{spec['no']:02d}" + ": " + spec["stage"] + " (" + spec["kr"] + ") | 860x" + str(spec["h"]) + "px]\n\n"
        + copy_result
        + "\n\n---\nDALL-E 3 Prompt (아래 내용을 ChatGPT에 그대로 붙여넣기):\n"
        "이 프롬프트로 이미지를 생성해줘:\n\n"
        + dalle_result
        + " The top 38% must be flat solid single-color background with no objects."
        " 860px width, " + str(spec["h"]) + "px height. No text in image."
    )
    return final

# ── 사이드바 ─────────────────────────────────────────────────
with st.sidebar:
    st.markdown("## 📡 소싱레이더")
    st.markdown("---")
    st.markdown("#### 소싱 설정")
    st.multiselect("소싱 업체",options=["도매매","도매꾹"],default=["도매매","도매꾹"],key="sourcing_sites")
    st.selectbox("검색 수량",list(FETCH_PRESETS.keys()),index=1,key="fetch_preset")
    st.markdown("#### 판매 전략")
    pname=st.selectbox("판매 플랫폼",list(PLATFORM_FEE.keys()))
    mname=st.select_slider("마진 전략",options=list(MARGIN_MAP.keys()))
    fee=PLATFORM_FEE[pname]; mg=MARGIN_MAP[mname]
    st.markdown(f"""<div style="background:#0f3460;border-radius:10px;padding:.8rem 1rem;margin-top:.5rem">
        <div style="color:#94a3b8;font-size:.72rem;font-weight:600">현재 설정</div>
        <div style="color:white;font-size:1rem;font-weight:700;margin-top:.2rem">수수료 {int(fee*100)}% / 목표마진 {int(mg*100)}%</div>
        <div style="color:#64748b;font-size:.72rem;margin-top:.2rem">배수 ÷{round(1-fee-mg,2)}</div>
    </div>""",unsafe_allow_html=True)
    st.markdown("---")
    tdf=load_tracked(); ttl=len(tdf)
    ap=int(apply_margin(tdf,fee,mg)["예상 순수익(원)"].mean()) if not tdf.empty else 0
    st.markdown("#### 관심 상품")
    c1,c2=st.columns(2); c1.metric("등록",ttl); c2.metric("평균수익",f"{ap:,}원")
    st.markdown("---")
    st.markdown("#### 텔레그램")
    try: tgok=st.secrets.get("TELEGRAM_BOT_TOKEN","") not in ["","봇토큰"]
    except: tgok=False
    st.markdown(f"상태: {'연동됨' if tgok else '미설정'}")
    _sbph=st.empty()
    if st.button("테스트 발송",use_container_width=True):
        ok=send_telegram_message(f"소싱레이더 테스트\n관심상품 {ttl}개")
        if ok: _sbph.success("✅ 완료")
        else: _sbph.error("❌ 실패")
    st.markdown("---")
    st.markdown(f"#### AI (Gemini)\n{'✅ 사용 가능' if GEMINI_KEY else '⚠️ 키 미설정'}")
    st.markdown("---")
    st.caption("소싱레이더 v8.1 | Blueprint v9.1")

st.markdown("""<div class="mh">
    <h1>📡 소싱레이더</h1>
    <p>도매매 · 도매꾹 실시간 통합 마진 분석 | AI 상세페이지 Blueprint v9.1</p>
</div>""",unsafe_allow_html=True)

tab1,tab2,tab3,tab4,tab5,tab6=st.tabs([
    "🔍 라이브 검색","⭐ 관심 상품","🔑 키워드 생성","🎨 AI 이미지 생성","📱 텔레그램","📖 가이드"])

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
            <div style="font-size:.8rem;margin-top:.3rem">업체등급: ⭐ 관심 등록 시 자동 조회 (관심 상품 탭에서 확인)</div>
        </div>""",unsafe_allow_html=True)
    else:
        raw=pd.DataFrame(st.session_state["live_results"])
        if raw.empty: st.info("검색 결과 없음")
        else:
            for col,d in [("seller_grade",""),("image_url","")]:
                if col not in raw.columns: raw[col]=d

            sc=raw["site"].value_counts().to_dict()
            st.markdown(f"<div style='color:#64748b;font-size:.85rem;margin-bottom:.5rem'>검색결과: "+" | ".join(f"{s} {n}개" for s,n in sc.items())+f" / 총 {len(raw):,}개</div>",unsafe_allow_html=True)

            fc1,fc2,fc3,fc4,fc5=st.columns([2,1,1,1.2,1.2])
            with fc1: kwf=st.text_input("재검색","",placeholder="상품명 필터...",label_visibility="collapsed")
            with fc2: sf=st.selectbox("소싱처",["전체"]+list(sc.keys()),label_visibility="collapsed")
            with fc3: stf=st.selectbox("상태",["전체","정상만"],label_visibility="collapsed")
            with fc4: sortc=st.selectbox("정렬",["예상 순수익(원)","공급가(원)","마진율(%)","추천 판매가(원)"],label_visibility="collapsed")
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
            maxp=int(df["예상 순수익(원)"].max()) if len(df)>0 else 0
            k1,k2,k3,k4=st.columns(4)
            k1.markdown(f'<div class="kc"><div class="kl">검색 결과</div><div class="kv">{len(df):,}</div><div class="ks">개</div></div>',unsafe_allow_html=True)
            k2.markdown(f'<div class="kc"><div class="kl">정상 판매</div><div class="kv" style="color:#16a34a">{ok_cnt:,}</div><div class="ks">개</div></div>',unsafe_allow_html=True)
            k3.markdown(f'<div class="kc"><div class="kl">평균 순수익</div><div class="kv">{avgp:,}</div><div class="ks">원/건</div></div>',unsafe_allow_html=True)
            k4.markdown(f'<div class="kc"><div class="kl">최고 순수익</div><div class="kv" style="color:#2563eb">{maxp:,}</div><div class="ks">원/건</div></div>',unsafe_allow_html=True)
            st.markdown("<br>",unsafe_allow_html=True)

            ds=50 if st.session_state["live_view"]=="table" else 18
            tpg=max(1,(len(df)+ds-1)//ds)
            pn=min(st.session_state["page_num"],tpg-1)
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
                        "업체등급":st.column_config.TextColumn("업체등급",help="🏅 버튼 또는 관심 등록 시 갱신"),
                    })
                chg=False
                for i in range(len(ed)):
                    if ed.iloc[i]["⭐ 관심"]!=disp.iloc[i]["⭐ 관심"]:
                        do_track(pdf.iloc[i].to_dict(),1 if ed.iloc[i]["⭐ 관심"] else 0); chg=True
                if chg: st.rerun()

            p1,p2,p3=st.columns([1,3,1])
            with p1:
                if st.button("이전",disabled=(pn==0),use_container_width=True):
                    st.session_state["page_num"]=pn-1; st.rerun()
            with p2:
                st.markdown(f"<div style='text-align:center;color:#64748b;font-size:.85rem;padding-top:.5rem'>{pn+1}/{tpg} | 총 {len(df):,}개</div>",unsafe_allow_html=True)
            with p3:
                if st.button("다음",disabled=(pn>=tpg-1),use_container_width=True):
                    st.session_state["page_num"]=pn+1; st.rerun()

# ══════════════════════════════════════════════════════════════
# TAB 2 — 관심 상품
# ══════════════════════════════════════════════════════════════
with tab2:
    tdf=load_tracked()
    if tdf.empty:
        st.markdown("""<div style="text-align:center;padding:3rem 0;color:#94a3b8">
            <div style="font-size:3rem">⭐</div><div style="font-size:1rem;margin-top:.5rem">관심 상품이 없습니다</div>
        </div>""",unsafe_allow_html=True)
    else:
        tm=len(tdf); tc=apply_margin(tdf,fee,mg)
        okm=len(tdf[tdf["status"]=="Y"])
        avm=round(tc["마진율(%)"].mean(),1)
        avp=int(tc[tc["status"]=="Y"]["예상 순수익(원)"].mean()) if okm>0 else 0
        k1,k2,k3,k4=st.columns(4)
        k1.markdown(f'<div class="kc"><div class="kl">관심 상품</div><div class="kv">{tm}</div><div class="ks">개</div></div>',unsafe_allow_html=True)
        k2.markdown(f'<div class="kc"><div class="kl">정상 판매</div><div class="kv" style="color:#16a34a">{okm}</div><div class="ks">개</div></div>',unsafe_allow_html=True)
        k3.markdown(f'<div class="kc"><div class="kl">평균 마진율</div><div class="kv" style="color:#7c3aed">{avm:.1f}%</div><div class="ks">목표마진 기준</div></div>',unsafe_allow_html=True)
        k4.markdown(f'<div class="kc"><div class="kl">월 예상수익(100건)</div><div class="kv" style="color:#2563eb">{avp*100:,}</div><div class="ks">원</div></div>',unsafe_allow_html=True)
        st.markdown("<br>",unsafe_allow_html=True)

        mv1,mv2,mv3=st.columns([2,1,1])
        with mv1: mf=st.text_input("상품명 검색","",placeholder="검색...",label_visibility="collapsed")
        with mv2: ms=st.selectbox("상태",["전체","정상만","품절만"],label_visibility="collapsed")
        with mv3:
            mvs=st.selectbox("보기",["🖼 카드 보기","📋 표 보기"],key="mv_sel",label_visibility="collapsed")
            st.session_state["mon_view"]="card" if "카드" in mvs else "table"

        mdf=tc.copy()
        mdf["상태"]=mdf["status"].apply(lambda x:"🟢 정상" if str(x)=="Y" else "❌ 품절")
        for col,d in [("seller_grade",""),("image_url","")]:
            if col not in mdf.columns: mdf[col]=d
        cache=st.session_state["grade_cache"]
        mdf["seller_grade"]=mdf.apply(lambda r:cache.get(str(r["product_id"]),str(r["seller_grade"]).replace("nan","")),axis=1)
        if mf: mdf=mdf[mdf["name"].str.contains(mf,case=False,na=False)]
        if ms=="정상만": mdf=mdf[mdf["status"]=="Y"]
        elif ms=="품절만": mdf=mdf[mdf["status"]!="Y"]

        tids_m=mdf["product_id"].astype(str).tolist()
        edm=None; cai=st.session_state.get("card_ai_selected",set())

        if st.session_state["mon_view"]=="card":
            render_cards(mdf,tids_m,"mn",lambda p,t:(upsert_tracked_product(p,t),st.rerun()),show_ai=True,ai_set=cai)
        else:
            mr=mdf.reset_index(drop=True)
            mr["AI선택"]=False; mr["해제"]=True
            if "updated_at" in mr.columns: mr["등록일"]=mr["updated_at"].apply(fmt_dt)
            keep=["AI선택","해제","site","product_id","name","supply_price","delivery_fee","상태","추천 판매가(원)","예상 순수익(원)","마진율(%)","seller_grade","등록일"]
            md=mr[[c for c in keep if c in mr.columns]].copy()
            md=md.rename(columns={"site":"소싱업체","product_id":"상품번호","name":"상품명",
                                   "supply_price":"공급가(원)","delivery_fee":"배송비(원)","seller_grade":"업체등급"})
            edm=st.data_editor(md,use_container_width=True,hide_index=True,key="te",
                column_config={
                    "AI선택":st.column_config.CheckboxColumn("AI선택",width="small"),
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
                },disabled=[c for c in md.columns if c not in ["AI선택","해제"]])
            tc2=False
            for i in range(len(edm)):
                if not edm.iloc[i]["해제"]:
                    pid_r=edm.iloc[i]["상품번호"]
                    m2=mr[mr["product_id"]==pid_r]
                    if not m2.empty: upsert_tracked_product(m2.iloc[0].to_dict(),0); tc2=True
            if tc2: st.rerun()

        st.markdown("<br>",unsafe_allow_html=True)
        _tp=st.empty()
        if st.button("📱 관심 상품 현황 텔레그램 전송",use_container_width=True):
            lines=[f"관심 상품 현황\n전체 {tm}개 / 정상 {okm}개 / 평균마진 {avm:.1f}%\n"]
            for _,row in tc.iterrows():
                lines.append(f"{'O' if row['status']=='Y' else 'X'} {row['name'][:22]} 판매가{int(row['추천 판매가(원)']):,}원 수익{int(row['예상 순수익(원)']):,}원")
            ok=tg_long("\n".join(lines),"관심 상품 현황")
            if ok: _tp.success("✅ 전송 완료")
            else: _tp.error("❌ 실패")

        st.markdown("---")
        st.markdown("#### 🤖 AI 소싱 분석")
        if not GEMINI_KEY:
            st.info("aistudio.google.com 에서 무료 키 발급 후 Secrets에 GEMINI_API_KEY 등록")
        else:
            sc2=0; sdf=pd.DataFrame()
            if st.session_state["mon_view"]=="card":
                sp=st.session_state.get("card_ai_selected",set()); sc2=len(sp)
                if sc2>0: sdf=tc[tc["product_id"].astype(str).isin(sp)].copy()
                if sc2>0: st.success(f"{sc2}개 선택됨")
                else: st.info("카드에서 🤖 AI분석 선택 체크 후 분석, 또는 전체 분석")
            elif edm is not None and "AI선택" in edm.columns:
                sr=edm[edm["AI선택"]==True]; sc2=len(sr)
                if sc2>0: sdf=tc[tc["product_id"].isin(sr["상품번호"].tolist())].copy()
                if sc2>0: st.success(f"{sc2}개 선택됨")
                else: st.info("표에서 AI선택 체크 후 분석, 또는 전체 분석")

            ba1,ba2=st.columns([2,1])
            with ba1: ab1=st.button("✨ 선택 상품 AI 분석",type="primary",use_container_width=True,disabled=(sc2==0))
            with ba2: ab2=st.button("📊 전체 AI 분석",use_container_width=True)

            if ab2:
                with st.spinner(f"전체 {tm}개 분석 중..."): result=compact_ai(tc,fee,mg,pname,mname)
                st.session_state["ai_result"]=result
            if ab1 and sc2>0:
                with st.spinner(f"{sc2}개 분석 중..."): result=compact_ai(apply_margin(sdf,fee,mg),fee,mg,pname,mname)
                st.session_state["ai_result"]=result

            if st.session_state.get("ai_result"):
                st.markdown("---"); st.markdown("**📊 AI 소싱 분석 결과**")
                rt=st.session_state["ai_result"]; st.markdown(rt)
                _aph=st.empty(); ac1,ac2=st.columns([2,1])
                with ac1:
                    if st.button("📱 분석 결과 텔레그램 전송",use_container_width=True,key="at"):
                        ok=tg_long(rt,"🤖 AI 소싱 분석")
                        if ok: _aph.success("✅ 전송 완료")
                        else: _aph.error("❌ 실패")
                with ac2:
                    if st.button("결과 초기화",use_container_width=True,key="ac"):
                        st.session_state["ai_result"]=None; st.rerun()

# ══════════════════════════════════════════════════════════════
# TAB 3 — 키워드 생성 (네이버/쿠팡 실시간 트렌드)
# ══════════════════════════════════════════════════════════════
with tab3:
    st.markdown("### 🔑 플랫폼별 키워드 생성")
    st.caption("네이버 쇼핑·쿠팡 실시간 인기 검색어를 수집해 플랫폼별 최적 키워드를 자동 생성합니다.")
    with st.container(border=True):
        kp=st.text_input("상품명",placeholder="예: 냉동 딸기 2.72kg",key="kw_prod")
        kf=st.text_area("주요 특징 (선택)",placeholder="예: 베이킹용, 스무디용, 대용량",height=70,key="kw_feat")
        kpls=st.multiselect("플랫폼 선택",options=list(PLATFORM_FEE.keys()),
                            default=["네이버 스마트스토어","쿠팡"],key="kw_pls")
        if st.button("🔑 키워드 생성",type="primary",use_container_width=True,
                     disabled=(not GEMINI_KEY or not kp or not kpls)):
            with st.spinner("네이버·쿠팡 실시간 검색어 수집 + AI 최적화 중..."):
                result=kw_gen(kp,kf,kpls)
            st.session_state["kw_result"]=result

    if st.session_state.get("kw_result"):
        st.markdown("---"); st.markdown("**🔑 플랫폼별 키워드 결과**")
        rt=st.session_state["kw_result"]
        kfi=st.text_input("결과 내 재검색","",placeholder="키워드 필터...",key="kw_fi")
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
                        copy_text=", ".join(kws)
                        chips=" ".join([f'<span class="kw-chip">{k}</span>' for k in kws])
                        cl,cr=st.columns([5,1])
                        with cl: st.markdown(f'<div style="margin:.3rem 0"><b>{lbl}:</b><br>{chips}</div>',unsafe_allow_html=True)
                        with cr: components.html(copy_btn(copy_text,"📋 복사"),height=44)
                    else: st.markdown(f"**{lbl}:** {cnt}")

        st.markdown("<br>",unsafe_allow_html=True)
        dc,tc2,cc=st.columns([2,2,1])
        with dc: st.download_button("💾 TXT 다운로드",data=rt,file_name=f"키워드_{kp[:20]}.txt",mime="text/plain",use_container_width=True)
        _tkph=st.empty()
        with tc2:
            if st.button("📱 텔레그램 전송",use_container_width=True,key="kt"):
                ok=tg_long(rt,"🔑 키워드 결과")
                if ok: _tkph.success("✅ 전송 완료")
                else: _tkph.error("❌ 실패")
        with cc:
            if st.button("초기화",use_container_width=True,key="kc"):
                st.session_state["kw_result"]=None; st.rerun()

# ══════════════════════════════════════════════════════════════
# TAB 4 — AI 이미지 생성 (Blueprint v9.1)
# ══════════════════════════════════════════════════════════════
with tab4:
    st.markdown("### 🎨 AI 상세페이지 이미지 프롬프트 생성")
    st.caption("Gemini로 DALL-E 3 프롬프트를 생성 → ChatGPT(GPT-4o)에 붙여넣어 이미지 생성")
    with st.container(border=True):
        ic1,ic2=st.columns(2)
        with ic1:
            ib=st.text_input("브랜드명",placeholder="예: 인터뷰어 토마토즙",key="ib")
            it=st.text_input("타겟 고객",placeholder="예: 20~40대 건강관리 직장인",key="it")
            icat=st.selectbox("카테고리",["식품/음료","뷰티/화장품","패션/의류","생활용품","디지털/가전","스포츠/레저","기타"],key="icat")
        with ic2:
            # ★ 이미지 직접 업로드 (URL 참조 제거)
            iup=st.file_uploader("상품 이미지 업로드 (선택 — AI가 분석해 프롬프트에 반영)",
                                 type=["jpg","jpeg","png","webp"],key="iup")
            if iup: st.image(iup,width=200,caption="업로드된 상품 이미지")
            st.caption("📌 이미지 업로드 시: Gemini Vision이 패키지 색상·형태를 분석해 DALL-E 3 프롬프트에 반영합니다.\n"
                       "📌 이미지 없어도: 텍스트 특징만으로 프롬프트 생성 가능합니다.")

        iff=st.text_area("상품 주요 특징",placeholder="1. 국산 토마토 100%\n2. NFC 착즙 방식\n3. 무첨가 원칙",height=120,key="iff")

    st.markdown("#### 생성할 이미지 선택")
    st.caption("Gemini 무료 한도(분당 15회)를 고려해 1~4개씩 나눠서 생성하세요.")
    ir=st.multiselect("이미지 선택",
                      options=[f"{s['no']:02d} — {s['stage']} ({s['kr']}) | 860×{s['h']}px" for s in IMAGE_SPEC],
                      default=["01 — HOOK (훅) | 860×2200px"],key="ir")

    if st.button("🎨 선택 이미지 프롬프트 생성",type="primary",use_container_width=True,
                 disabled=(not GEMINI_KEY or not ib or not iff or not ir)):
        sel_nos=[int(s.split(" — ")[0]) for s in ir]
        sel_specs=[s for s in IMAGE_SPEC if s["no"] in sel_nos]
        image_b64=""
        if iup:
            try: image_b64=base64.b64encode(iup.getvalue()).decode("utf-8")
            except: pass

        prog=st.progress(0,text="프롬프트 생성 시작...")
        existing=st.session_state.get("img_prompts",{})
        for i,spec in enumerate(sel_specs):
            prog.progress(i/len(sel_specs),text=f"Image {spec['no']:02d}: {spec['stage']} ({spec['kr']}) 생성 중...")
            result=gen_img_prompt(spec,ib,iff,it,icat,image_b64)
            if "429" in result:
                st.warning(f"Image {spec['no']}: 429 한도 초과. 60초 대기 후 재시도...")
                _time.sleep(60)
                result=gen_img_prompt(spec,ib,iff,it,icat,image_b64)
            existing[spec["no"]]=result
            if i<len(sel_specs)-1: _time.sleep(4)
        st.session_state["img_prompts"]=existing
        prog.progress(1.0,text=f"완료! {len(sel_specs)}개 생성됨")
        st.rerun()

    if st.session_state.get("img_prompts"):
        prompts=st.session_state["img_prompts"]
        st.markdown("---")
        st.markdown(f"**🎨 생성된 프롬프트 ({len(prompts)}개) — ChatGPT(GPT-4o)에 복사해서 붙여넣기**")
        all_texts=[]
        for no in sorted(prompts.keys()):
            sp=[s for s in IMAGE_SPEC if s["no"]==no]
            sz=f" | 860×{sp[0]['h']}px" if sp else ""
            kr=sp[0]['kr'] if sp else ""
            content=prompts[no]
            all_texts.append(f"[Image {no:02d}: {IMAGE_SPEC[no-1]['stage']} ({kr})]\n{content}")
            with st.expander(f"🖼 Image {no:02d}: {IMAGE_SPEC[no-1]['stage']} ({kr}){sz}",expanded=False):
                st.markdown(content)
                dm=_re.search(r"DALL-E 3 Prompt:\s*\n?(Photorealistic[^\[]*)",content,_re.I|_re.S)
                if dm:
                    dp=dm.group(1).strip()
                    gpt_text=f"이 프롬프트로 이미지를 생성해줘:\n\n{dp}"
                    st.markdown("**📋 ChatGPT 붙여넣기용 (복사 후 ChatGPT에 붙여넣기):**")
                    st.code(gpt_text,language=None)
                    c1,c2=st.columns([1,1])
                    with c1: components.html(copy_btn(gpt_text,f"📋 Image {no:02d} 복사"),height=44)
                    with c2: st.download_button(f"💾 저장",data=gpt_text,
                                                file_name=f"{ib}_{no:02d}_{IMAGE_SPEC[no-1]['stage']}.txt",
                                                mime="text/plain",key=f"dl_{no}")

        st.markdown("<br>",unsafe_allow_html=True)
        all_dl=f"소싱레이더 AI 상세페이지 Blueprint v9.1\n브랜드: {ib}\n생성일: {datetime.now().strftime('%Y.%m.%d %H:%M')}\n{'='*60}\n\n"+"\n\n".join(all_texts)
        dc2,cc2=st.columns([3,1])
        with dc2: st.download_button("💾 전체 프롬프트 TXT 다운로드",data=all_dl,
                                     file_name=f"{ib}_상세페이지_v91.txt",mime="text/plain",use_container_width=True)
        with cc2:
            if st.button("전체 초기화",use_container_width=True,key="ic"):
                st.session_state["img_prompts"]={}; st.rerun()

        st.info("💡 ChatGPT 사용법\n"
                "1. '📋 복사' 버튼 클릭\n"
                "2. chatgpt.com → GPT-4o 선택\n"
                "3. 붙여넣기 → Enter\n"
                "4. 이미지 우클릭 → 저장\n"
                "무료: 하루 일정 횟수 | Plus($20/월): 무제한")

# ══════════════════════════════════════════════════════════════
# TAB 5 — 텔레그램
# ══════════════════════════════════════════════════════════════
with tab5:
    st.markdown("### 📱 텔레그램 설정")
    ca,cb=st.columns(2)
    with ca:
        st.markdown("""
봇 만들기
1. 텔레그램 → @BotFather 검색
2. /newbot → 이름 설정 → 토큰 복사

채팅방 ID 확인
https://api.telegram.org/bot[토큰]/getUpdates
chat.id 뒤 숫자

다중 수신자
TELEGRAM_CHAT_IDS에 콤마로 여러 ID 입력
(친구가 먼저 봇에게 /start 보내야 함)
        """)
    with cb:
        st.code("""DOMEGGOOK_API_KEY  = "API키"
TELEGRAM_BOT_TOKEN = "봇토큰"
TELEGRAM_CHAT_IDS  = "내ID,친구ID"
GEMINI_API_KEY     = "제미나이키(무료)"
""",language="toml")
        _t5ph=st.empty()
        tm2=st.text_input("테스트 메시지",value="소싱레이더 연동 테스트")
        if st.button("테스트 발송",type="primary",use_container_width=True):
            ok=send_telegram_message(tm2)
            if ok: _t5ph.success("✅ 성공")
            else: _t5ph.error("❌ 실패")

# ══════════════════════════════════════════════════════════════
# TAB 6 — 가이드
# ══════════════════════════════════════════════════════════════
with tab6:
    st.markdown("### 📖 가이드")
    with st.expander("업체등급 확인 방법"):
        st.markdown("""
⭐ 관심 등록 시 상세 API가 자동 호출되어 등급이 저장됩니다.
관심 상품 탭에서 업체등급을 확인하세요.

등급: ⭐S > 🔵A > 🟢B > 🟡C > 🟠D > 🔴E
B등급 이상 공급사 소싱을 권장합니다.
        """)
    with st.expander("AI 이미지 생성 사용법"):
        st.markdown("""
1. 브랜드명, 타겟, 카테고리, 특징 입력
2. 상품 이미지 업로드 (선택 — AI가 패키지 색상/형태 분석)
3. 생성할 이미지 번호 선택 (1~4개 권장, Gemini 한도 고려)
4. 생성 후 '📋 복사' 버튼 → ChatGPT(GPT-4o) 붙여넣기 → 이미지 생성
5. 이미지 저장: {브랜드}_01_HOOK.png ... {브랜드}_12_CTA.png 순서로

Gemini 429 오류: 1분 후 재시도 또는 이미지 수 줄이기
ChatGPT: chatgpt.com (무료 일일 한도 / Plus $20/월 무제한)
        """)
    with st.expander("플랫폼별 수수료"):
        st.markdown("""
| 플랫폼 | 수수료 | 비고 |
|---|---|---|
| 네이버 스마트스토어 | 6% | 판매2.73%+결제3.3% |
| 쿠팡 | 11% | 카테고리별 4~10.8% |
| 11번가 | 12% | 카테고리별 6~13% |
| G마켓 | 12% | 카테고리별 4~15% |
| 옥션 | 12% | G마켓 동일 구조 |
        """)
    with st.expander("키워드 복사 사용법"):
        st.markdown("""
📋 복사 버튼 클릭 → 클립보드 자동 복사 → Ctrl+V 붙여넣기
형식: 키워드1, 키워드2, 키워드3 (쉼표 구분)
스마트스토어/쿠팡 상품 등록 태그 입력창에 그대로 붙여넣기 가능
        """)
