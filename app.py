import re as _re
import streamlit as st
import streamlit.components.v1 as components
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
.grade-badge{display:inline-block;padding:2px 8px;border-radius:6px;font-size:.78rem;font-weight:600}
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
    "네이버 스마트스토어":{"format":"브랜드+상품유형+핵심특징+타겟/용도","max_len":100,"max_kw":10},
    "쿠팡":{"format":"핵심상품명+용량/수량+주요특징","max_len":50,"max_kw":8},
    "11번가":{"format":"브랜드+상품명+모델명/규격+수량","max_len":80,"max_kw":10},
    "G마켓":{"format":"브랜드+상품유형+특징+구성/용량","max_len":80,"max_kw":10},
    "옥션":{"format":"브랜드+상품유형+구성수량+할인/혜택","max_len":80,"max_kw":10},
}

IMAGE_SPEC=[
    {"no":1,"stage":"HOOK","kr":"훅","h":2200,"purpose":"Hero product, 3초 내 시선 확보"},
    {"no":2,"stage":"Painpoint","kr":"문제 공감","h":1800,"purpose":"고객 현실 문제 자극"},
    {"no":3,"stage":"Solution","kr":"해결 제안","h":2000,"purpose":"제품 등장, Before/After"},
    {"no":4,"stage":"USP1","kr":"핵심 가치 1","h":1800,"purpose":"가장 강력한 USP"},
    {"no":5,"stage":"USP2","kr":"핵심 가치 2","h":1800,"purpose":"기능적 차별화"},
    {"no":6,"stage":"USP3","kr":"핵심 가치 3","h":1800,"purpose":"성분/원천 기술"},
    {"no":7,"stage":"USP4","kr":"핵심 가치 4","h":1800,"purpose":"감성/편의 가치"},
    {"no":8,"stage":"TPO","kr":"활용성","h":1800,"purpose":"일상/상황별 사용 장면"},
    {"no":9,"stage":"Certification","kr":"신뢰","h":2500,"purpose":"구매 의심 제거"},
    {"no":10,"stage":"SpecsInfo","kr":"상세 정보","h":2800,"purpose":"구매 판단 완료"},
    {"no":11,"stage":"Audience","kr":"추천 대상","h":1600,"purpose":"반품 감소, 구매 확신"},
    {"no":12,"stage":"CTA","kr":"행동 유도","h":1800,"purpose":"최종 구매 유도"},
]

for k,v in {
    "live_results":[],"show_results":False,"search_error":None,
    "page_num":0,"ai_result":None,
    "live_view":"card","mon_view":"card",
    "kw_result":None,"img_prompt":None,
    "card_ai_selected":set(),
    "grade_cache":{},   # ★ 등급 캐시: product_id → grade
}.items():
    if k not in st.session_state:
        st.session_state[k]=v

# ── 헬퍼 ─────────────────────────────────────────────────────
def fmt_dt(dt_str):
    if not dt_str or str(dt_str) in ("nan","None",""): return ""
    try: return datetime.strptime(str(dt_str)[:19],"%Y-%m-%d %H:%M:%S").strftime("%y.%m.%d")
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
    kw   =st.session_state.get("search_kw","").strip()
    cat  =CATEGORY_MAP[st.session_state["cat_main"]][st.session_state["cat_sub"]]
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

    if "온채널" in sites:
        errors.append("온채널: 현재 클라우드 환경에서 접근 불가 (도매매/도매꾹 결과는 정상)")

    if errors: st.session_state["search_error"]=" | ".join(errors)
    if not results and not [e for e in errors if "도매" in e]:
        if not st.session_state.get("search_error"):
            st.session_state["search_error"]="검색 결과 없음"
    elif results:
        df=pd.DataFrame(results).drop_duplicates(subset=["product_id"])
        for col,default in [("seller_grade",""),("image_url","")]:
            if col not in df.columns: df[col]=default
        # 캐시된 등급 복원
        cache=st.session_state.get("grade_cache",{})
        df["seller_grade"]=df.apply(
            lambda r: cache.get(str(r["product_id"]),r["seller_grade"]), axis=1)
        st.session_state["live_results"]=df.to_dict("records")
    st.session_state["show_results"]=True

def reset_all():
    st.session_state.update({"search_kw":"","live_results":[],"show_results":False,
                              "search_error":None,"page_num":0,"ai_result":None,"card_ai_selected":set()})
    st.rerun()

def do_track(prod, is_track):
    """관심 등록 시 상세 API → 등급 획득 → DB 저장 + 캐시 저장"""
    if is_track and client and prod.get("site") in ["도매매","도매꾹"]:
        detail=client.fetch_item_detail(str(prod["product_id"]))
        if detail:
            for k,v in detail.items():
                if v or v==0: prod[k]=v
            # ★ 등급 캐시 저장
            if detail.get("seller_grade"):
                cache=st.session_state.get("grade_cache",{})
                cache[str(prod["product_id"])]=detail["seller_grade"]
                st.session_state["grade_cache"]=cache
    upsert_tracked_product(prod, is_track)

def get_product_url(row):
    site=row.get("site",""); pid=str(row.get("product_id",""))
    if site in ["도매꾹","도매매"]:
        mkt="" if site=="도매꾹" else "&market=supply"
        return f"https://domeggook.com/main/item/itemView.php?no={pid}{mkt}"
    elif pid.startswith("OC_"):
        return f"https://www.onch3.co.kr/goods_view.php?vnum={pid[3:]}"
    return ""

def grade_color(grade):
    g=grade[0].upper() if grade and grade[0].isalpha() else ""
    return {"S":"#f59e0b","A":"#3b82f6","B":"#22c55e","C":"#eab308","D":"#f97316","E":"#ef4444"}.get(g,"#94a3b8")

def copy_button_html(text_to_copy: str, label: str = "📋 복사") -> str:
    """★ st.components를 통한 실제 클립보드 복사 버튼 HTML"""
    safe_text = text_to_copy.replace("\\", "\\\\").replace("`", "\\`").replace("'", "\\'").replace('"', '\\"')
    return f"""
<button onclick="
  const el=document.createElement('textarea');
  el.value='{safe_text}';
  document.body.appendChild(el);
  el.select();
  document.execCommand('copy');
  document.body.removeChild(el);
  this.textContent='✅ 복사됨';
  setTimeout(()=>this.textContent='{label}',2000);
" style="
  background:#3b82f6;color:white;border:none;border-radius:6px;
  padding:5px 12px;font-size:.82rem;cursor:pointer;
  white-space:nowrap;font-weight:600;
">{label}</button>"""

def render_cards(df, tracked_ids, id_prefix, on_toggle,
                 show_ai_select=False, ai_selected_set=None):
    per_row=3
    for i in range(0,len(df),per_row):
        cols=st.columns(per_row)
        for ci,(_,row) in enumerate(df.iloc[i:i+per_row].iterrows()):
            with cols[ci]:
                # ★ 캐시에서 등급 우선 적용
                cache=st.session_state.get("grade_cache",{})
                grade=cache.get(str(row["product_id"]),str(row.get("seller_grade","")).strip())
                img=str(row.get("image_url","")).strip()
                profit=int(row.get("예상 순수익(원)",0))
                sale=int(row.get("추천 판매가(원)",0))
                mp=float(row.get("마진율(%)",0))
                pid=str(row["product_id"])
                is_t=pid in tracked_ids
                prod_url=get_product_url(row)
                gc=grade_color(grade)

                if img and img.startswith("http"):
                    if prod_url:
                        st.markdown(f'<a href="{prod_url}" target="_blank"><img src="{img}" '
                                    f'style="width:100%;border-radius:8px;cursor:pointer;margin-bottom:6px"/></a>',
                                    unsafe_allow_html=True)
                    else:
                        try: st.image(img,width=220)
                        except: st.markdown("📦")
                else:
                    link_attr=f'href="{prod_url}" target="_blank"' if prod_url else ""
                    st.markdown(f'<a {link_attr} style="text-decoration:none"><div style="height:90px;'
                                f'background:#f1f5f9;border-radius:8px;display:flex;align-items:center;'
                                f'justify-content:center;font-size:2.5rem;margin-bottom:6px;cursor:pointer">📦</div></a>',
                                unsafe_allow_html=True)

                name_link=(f'<a href="{prod_url}" target="_blank" style="color:#1e293b;text-decoration:none">'
                           f'{row["name"][:30]}</a>' if prod_url else row["name"][:30])
                grade_html=(f'<span class="grade-badge" style="background:{gc}22;color:{gc}">'
                            f'{grade}</span>' if grade else
                            '<span style="color:#94a3b8;font-size:.72rem">등급 미조회</span>')

                st.markdown(f"""
<div style="font-size:.82rem;font-weight:500;white-space:nowrap;overflow:hidden;
    text-overflow:ellipsis;margin-bottom:3px" title="{row['name']}">{name_link}</div>
<div style="font-size:.7rem;color:#94a3b8;margin-bottom:3px">{row.get('site','')} | {pid}</div>
<div style="font-size:.75rem;color:#475569;margin-bottom:2px">
    공급가 <b>{int(row['supply_price']):,}원</b> 배송비 <b>{int(row['delivery_fee']):,}원</b></div>
<div style="font-size:.9rem;font-weight:700;color:#2563eb;margin-bottom:3px">
    판매가 {sale:,}원 &nbsp; 순수익 {profit:,}원</div>
<div style="font-size:.72rem;color:#64748b;display:flex;align-items:center;gap:6px">
    마진 <b>{mp:.1f}%</b> &nbsp; 등급 {grade_html} &nbsp; {row.get('상태','')}
</div>""", unsafe_allow_html=True)

                if show_ai_select and ai_selected_set is not None:
                    ai_checked=pid in ai_selected_set
                    new_checked=st.checkbox("🤖 AI분석 선택",value=ai_checked,key=f"ai_chk_{id_prefix}_{pid}")
                    if new_checked!=ai_checked:
                        if new_checked: ai_selected_set.add(pid)
                        else: ai_selected_set.discard(pid)
                        st.session_state["card_ai_selected"]=ai_selected_set

                label="⭐ 등록됨" if is_t else "☆ 관심 등록"
                if st.button(label,key=f"{id_prefix}_card_{pid}",use_container_width=True):
                    on_toggle(row.to_dict(),0 if is_t else 1); st.rerun()

def send_tg_long(text,prefix="📡 소싱레이더"):
    import time as _t
    chunks=[text[i:i+3800] for i in range(0,len(text),3800)]
    total=len(chunks); ok=True
    for i,chunk in enumerate(chunks):
        hdr=prefix if total==1 else f"{prefix} ({i+1}/{total})"
        if not send_telegram_message(f"{hdr}\n\n{chunk}"): ok=False
        if i<len(chunks)-1: _t.sleep(0.5)
    return ok

def gemini_call(prompt,max_tokens=2000):
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
    except Exception as e: return f"AI 연결 오류: {e}"

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

def generate_keywords(prod_name,features,platforms):
    guide_str="\n".join([f"[{p}] 형식={PLATFORM_KW_GUIDE[p]['format']}, 최대{PLATFORM_KW_GUIDE[p]['max_len']}자" for p in platforms])
    prompt=f"""이커머스 SEO 전문가. 아래 상품의 플랫폼별 최적 키워드를 생성하세요.
상품명: {prod_name}
주요 특징: {features}
{guide_str}

각 플랫폼별 출력 (## 없이):
[플랫폼명]
추천 상품명: (최적 상품명)
핵심 키워드: 키워드1, 키워드2, 키워드3, 키워드4, 키워드5
롱테일 키워드: 키워드1, 키워드2, 키워드3
태그: 태그1, 태그2, 태그3, 태그4, 태그5
등록 팁: 한줄

플랫폼 간 구분: ---"""
    return gemini_call(prompt,2000)

def fetch_url_content(url:str)->str:
    if not url or not url.startswith("http"): return ""
    try:
        from bs4 import BeautifulSoup
        resp=req.get(url,headers={"User-Agent":"Mozilla/5.0"},timeout=10)
        if resp.status_code==200:
            resp.encoding=resp.apparent_encoding
            soup=BeautifulSoup(resp.text,"html.parser")
            for tag in soup(["script","style","nav","footer","header"]): tag.decompose()
            # 이미지 URL도 수집
            imgs=[i.get("src","") for i in soup.select("img[src]") if i.get("src","").startswith("http")][:3]
            text=soup.get_text(separator="\n",strip=True)[:1500]
            img_ref="\n대표 이미지 URL:\n"+"\n".join(imgs) if imgs else ""
            return text+img_ref
    except Exception as e: print(f"[URL fetch] {e}")
    return ""

def generate_image_prompts_v91(brand, product_url, product_image_url, features, target, category):
    """
    SourcingRadar AI Master Blueprint v9.1 (개정판)
    개선사항:
    - 전환율 65 → 목표 85: 가격/혜택/한정성 카피 강화
    - 법적 안정성 55 → 목표 80: 과장 금지, 실증 기반 문구 강제
    - 스마트스토어 실전성 70 → 목표 90: 모바일 최적화, 스크롤 흐름
    - 상품 URL 이미지 실제 참조
    """
    url_content=""
    if product_url and product_url.startswith("http"):
        url_content=fetch_url_content(product_url)
        if url_content:
            url_content=f"\n\n[참고 URL 실제 내용 — AI가 이 정보를 이미지 컨셉에 반영할 것]\n{url_content}"

    image_ref=""
    if product_image_url and product_image_url.startswith("http"):
        image_ref=f"\n\n[상품 대표 이미지 URL — 프롬프트에 반드시 포함할 것]\n{product_image_url}"

    specs_table="\n".join([
        f"Image{s['no']:02d} [{s['stage']}] ({s['kr']}): 860×{s['h']}px — {s['purpose']}"
        for s in IMAGE_SPEC])

    prompt=f"""You are a senior Korean e-commerce visual strategist and conversion rate optimization specialist.
Generate 12 DALL-E 3 optimized image prompts for a Naver Smartstore detail page.

Follow SourcingRadar AI Master Blueprint v9.1 (Revised for Higher Conversion):

PRODUCT INFORMATION:
Brand: {brand}
Category: {category}
Target Audience: {target}
Key Features: {features}{url_content}{image_ref}

CRITICAL V9.1 IMPROVEMENTS (must apply to all prompts):

[Conversion Rate +20pts fix — was 65, target 85]
Include in relevant images: price anchor visual, limited-time urgency element, comparison with generic alternatives, clear benefit quantification ("XX% 절감", "하루 1개" etc.)

[Legal Safety +25pts fix — was 55, target 80]  
STRICTLY PROHIBIT in all prompts: fake review counts, fabricated ratings, unverified certifications, unproven medical claims, competitor bashing with names. Only show verified facts provided by user.

[Smartstore Practicality +20pts fix — was 70, target 90]
Mobile-first design: large text zones, single focal point per image, vertical scroll optimized, high contrast background/foreground, avoid busy collage layouts.

MANDATORY TECHNICAL RULES:
1. Every prompt MUST include: "The top 40% of the vertical canvas is filled with a FLAT SOLID single-color background — no textures, gradients, or patterns — reserved exclusively for Korean text overlay in post-production."
2. Width: 860px fixed. Use exact heights from spec table.
3. No text in the generated image (text is added in post-production)
4. No competitor brand names or logos
5. Photorealistic commercial photography style only
6. If product image URL is provided above, reference it as: "Product appearance references: [URL]"

IMAGE SPEC TABLE:
{specs_table}

OUTPUT FORMAT (repeat for all 12 images):

[Image N: STAGE]
한국어 섹션명: (Korean)
목적: (Korean purpose)
이미지 규격: 860×Hpx
메인 카피 (텍스트 오버레이용 한국어): (15~25자, 숫자 우선)
서브 카피: (1~2문장 한국어)
보조 포인트 3개: 포인트1 / 포인트2 / 포인트3
전환율 강화 요소: (이 이미지에서 구매를 유도하는 구체적 요소)
법적 안전 체크: (과장/허위 없음 확인)
DALL-E 3 Prompt:
[Complete English prompt starting with "Photorealistic commercial photography..." including the top-40%-solid-background rule and exact pixel dimensions. Minimum 80 words.]

Generate all 12 images. Start with Image 1."""

    return gemini_call(prompt,5000)

def build_download_text(brand,prompt_text):
    return f"""소싱레이더 AI 상세페이지 마스터 가이드북 v9.1 (개정판)
브랜드: {brand}
생성일: {datetime.now().strftime('%Y.%m.%d %H:%M')}
규격: 860px 고정 | 12개 이미지 | DALL-E 3 최적화
개선: 전환율+20pt / 법적안전성+25pt / 스마트스토어실전성+20pt
{'='*60}

ChatGPT 사용법:
1. 각 [Image N]의 'DALL-E 3 Prompt:' 이하 텍스트 전체 복사
2. ChatGPT (GPT-4o) 대화창에 붙여넣기
3. Enter → 이미지 생성 확인
4. 이미지 우클릭 → 저장
5. 파일명: {brand}_01_HOOK.png ... {brand}_12_CTA.png

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
        st.caption("⚠️ 온채널: 현재 클라우드 환경 차단으로 검색 불가")
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
    # ★ 사이드바 전송 결과 — placeholder 고정
    _sb_ph=st.empty()
    if st.button("테스트 발송",use_container_width=True,key="sb_tg"):
        ok=send_telegram_message(f"소싱레이더 연동 테스트\n관심상품 {total_t}개")
        if ok: _sb_ph.success("✅ 발송 완료")
        else:  _sb_ph.error("❌ 발송 실패")
    st.markdown("---")
    st.markdown(f"#### AI (Gemini 무료)\n{'사용 가능' if GEMINI_KEY else 'GEMINI_API_KEY 미설정'}")
    st.markdown("---")
    st.caption("소싱레이더 v7.1 | Blueprint v9.1")

# ── 헤더 ────────────────────────────────────────────────────
st.markdown("""<div class="main-header">
    <h1>📡 소싱레이더</h1>
    <p>도매매 도매꾹 실시간 통합 마진 분석 | AI 상세페이지 Blueprint v9.1</p>
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
        # 도매매/도매꾹 결과가 있어도 온채널 경고만 표시
        err=st.session_state["search_error"]
        if "온채널" in err and st.session_state.get("live_results"):
            st.info(f"ℹ️ {err}")
        else:
            st.warning(err)

    if not st.session_state["show_results"]:
        st.markdown("""<div style="text-align:center;padding:3rem 0;color:#94a3b8">
            <div style="font-size:3rem">📦</div>
            <div style="font-size:1rem;margin-top:.5rem">키워드를 입력하고 검색하세요</div>
            <div style="font-size:.8rem;margin-top:.3rem">업체등급: 🏅 등급 조회 버튼 또는 ⭐ 관심 등록 시 자동 갱신</div>
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
                            updated_df=pd.DataFrame(updated)
                            # 등급 캐시 업데이트
                            cache=st.session_state.get("grade_cache",{})
                            for _,row in updated_df.iterrows():
                                if row.get("seller_grade"):
                                    cache[str(row["product_id"])]=row["seller_grade"]
                            st.session_state["grade_cache"]=cache
                            st.session_state["live_results"]=updated_df.to_dict("records")
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
                # 캐시 등급 적용
                cache=st.session_state.get("grade_cache",{})
                page_df["seller_grade"]=page_df.apply(
                    lambda r:cache.get(str(r["product_id"]),r.get("seller_grade","")),axis=1)
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
                            help="🏅 등급 조회 버튼 또는 ⭐ 관심 등록 시 갱신"),
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
        # ★ 캐시된 등급 반영
        cache=st.session_state.get("grade_cache",{})
        mdf["seller_grade"]=mdf.apply(
            lambda r: cache.get(str(r["product_id"]),str(r["seller_grade"]).replace("nan","")), axis=1)
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
            mdf_reset=mdf.reset_index(drop=True)
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
                },
                disabled=[c for c in mdf_disp.columns if c not in ["AI선택","해제"]],
            )
            track_changed=False
            for i in range(len(edited_m)):
                if not edited_m.iloc[i]["해제"]:
                    pid_to_remove=edited_m.iloc[i]["상품번호"]
                    match=mdf_reset[mdf_reset["product_id"]==pid_to_remove]
                    if not match.empty:
                        upsert_tracked_product(match.iloc[0].to_dict(),0); track_changed=True
            if track_changed: st.rerun()

        st.markdown("<br>",unsafe_allow_html=True)
        _tg2_ph=st.empty()
        if st.button("📱 관심 상품 현황 텔레그램 전송",use_container_width=True):
            lines=[f"관심 상품 현황\n전체 {total_m}개 / 정상 {ok_m}개 / 평균마진 {avg_m:.1f}%\n"]
            for _,row in t_calc.iterrows():
                icon="O" if row["status"]=="Y" else "X"
                lines.append(f"{icon} {row['name'][:22]} 판매가{int(row['추천 판매가(원)']):,}원 수익{int(row['예상 순수익(원)']):,}원")
            ok_sent=send_tg_long("\n".join(lines),"관심 상품 현황")
            if ok_sent: _tg2_ph.success("✅ 전송 완료")
            else: _tg2_ph.error("❌ 전송 실패")

        st.markdown("---")
        st.markdown("#### 🤖 AI 소싱 분석")
        if not GEMINI_KEY:
            st.info("aistudio.google.com 에서 무료 키 발급 후 Secrets에 GEMINI_API_KEY 등록")
        else:
            sel_count=0; sel_df=pd.DataFrame()
            if st.session_state["mon_view"]=="card":
                sel_pids=st.session_state.get("card_ai_selected",set()); sel_count=len(sel_pids)
                if sel_count>0: sel_df=t_calc[t_calc["product_id"].astype(str).isin(sel_pids)].copy()
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
                _ai_tg_ph=st.empty()
                tg_c,clr_c=st.columns([2,1])
                with tg_c:
                    if st.button("📱 분석 결과 텔레그램 전송",use_container_width=True,key="ai_tg"):
                        ok_sent=send_tg_long(result_text,"🤖 AI 소싱 분석")
                        if ok_sent: _ai_tg_ph.success("✅ 전송 완료")
                        else: _ai_tg_ph.error("❌ 전송 실패")
                with clr_c:
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
    if st.button("🔑 키워드 생성",type="primary",use_container_width=True,
                 disabled=(not GEMINI_KEY or not kw_prod or not kw_platforms)):
        actual_name=(st.session_state.get("kw_from_live","직접 입력")
                     if st.session_state.get("live_results") and
                     st.session_state.get("kw_from_live","직접 입력")!="직접 입력"
                     else kw_prod)
        with st.spinner("키워드 생성 중..."): result=generate_keywords(actual_name,kw_feat,kw_platforms)
        st.session_state["kw_result"]=result
    st.markdown('</div>',unsafe_allow_html=True)

    if st.session_state.get("kw_result"):
        st.markdown("---")
        st.markdown("**🔑 플랫폼별 키워드 결과**")
        result_text=st.session_state["kw_result"]
        kw_inner=st.text_input("결과 내 재검색","",placeholder="키워드 입력 시 해당 플랫폼만 표시...",key="kw_inner_filter")
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
                            col_l,col_r=st.columns([5,1])
                            with col_l:
                                st.markdown(f'<div style="margin:.3rem 0"><b>{label}:</b><br>{chips}</div>',
                                            unsafe_allow_html=True)
                            with col_r:
                                # ★ execCommand 방식 — Streamlit iframe에서도 동작
                                components.html(copy_button_html(copy_text,f"📋"),height=40)
                        else:
                            st.markdown(f"**{label}:** {content}")
                    else:
                        st.markdown(line)

        st.markdown("<br>",unsafe_allow_html=True)
        dl_kw,_tg_kw_ph_col,clr_kw=st.columns([2,2,1])
        with dl_kw:
            st.download_button("💾 전체 TXT 다운로드",data=result_text,
                               file_name=f"키워드_{kw_prod[:20]}.txt",mime="text/plain",use_container_width=True)
        _tg_kw_ph=st.empty()
        with _tg_kw_ph_col:
            if st.button("📱 텔레그램 전송",use_container_width=True,key="kw_tg"):
                ok_sent=send_tg_long(result_text,"🔑 키워드 생성 결과")
                if ok_sent: _tg_kw_ph.success("✅ 전송 완료")
                else: _tg_kw_ph.error("❌ 전송 실패")
        with clr_kw:
            if st.button("초기화",use_container_width=True,key="kw_clr"):
                st.session_state["kw_result"]=None; st.rerun()

# ══════════════════════════════════════════════════════════════
# TAB 4: AI 이미지 생성 (Blueprint v9.1 개정판)
# ══════════════════════════════════════════════════════════════
with tab4:
    st.markdown("### 🎨 AI 상세페이지 이미지 프롬프트 생성")

    # 점수 개선 현황
    col_score1,col_score2=st.columns(2)
    with col_score1:
        st.markdown("""
        **v9.0 기준 점수 (현황)**
        | 항목 | 점수 |
        |---|---|
        | 구도 | 90 |
        | AI 생성성 | 95 |
        | 상세페이지 적합성 | 85 |
        | 전환율 | 65 ⚠️ |
        | 스마트스토어 실전성 | 70 ⚠️ |
        | 법적 안정성 | 55 ⚠️ |
        """)
    with col_score2:
        st.markdown("""
        **v9.1 개정 목표 점수**
        | 항목 | 목표 | 개선 방법 |
        |---|---|---|
        | 구도 | 90 | 유지 |
        | AI 생성성 | 95 | 유지 |
        | 상세페이지 적합성 | 90 | ↑ |
        | 전환율 | 85 | 가격앵커+한정성+수치화 |
        | 스마트스토어 실전성 | 90 | 모바일최적화+스크롤흐름 |
        | 법적 안정성 | 80 | 과장금지+실증기반 강제 |
        """)

    st.markdown('<div class="ai-section">',unsafe_allow_html=True)
    img_col1,img_col2=st.columns(2)
    with img_col1:
        img_brand=st.text_input("브랜드명",placeholder="예: 인터뷰어 토마토즙",key="img_brand")
        img_target=st.text_input("타겟 고객",placeholder="예: 20~40대 건강관리에 관심있는 직장인",key="img_target")
        img_category=st.selectbox("상품 카테고리",
                                  ["식품/음료","뷰티/화장품","패션/의류","생활용품",
                                   "디지털/가전","스포츠/레저","반려동물","기타"],key="img_category")
    with img_col2:
        img_url=st.text_input("참고 상품 URL (실제 페이지 내용 + 이미지 자동 참조)",
                              placeholder="https://... 입력 시 실제 URL 크롤링 후 AI 반영",key="img_url")
        img_image_url=st.text_input("상품 이미지 URL (직접 입력 또는 자동 수집됨)",
                                    placeholder="https://img.domeggook.com/... 또는 비워두기",
                                    key="img_image_url")
        st.caption("💡 v9.1: 톤앤매너 자동 결정 | 전환율·법적안전성·실전성 대폭 개선")

    img_features=st.text_area("상품 주요 특징",
        placeholder="1. 국산 토마토 100% 사용\n2. NFC 착즙 방식\n3. 무첨가 원칙 ...",
        height=150,key="img_features")

    # 검색 결과에서 이미지 URL 자동 가져오기
    if st.session_state.get("live_results") and not img_image_url:
        live_imgs=[r.get("image_url","") for r in st.session_state["live_results"] if r.get("image_url","").startswith("http")]
        if live_imgs:
            st.info(f"💡 검색 결과 첫 번째 상품 이미지를 자동으로 참조합니다: {live_imgs[0][:60]}...")

    if st.button("🎨 12개 이미지 프롬프트 생성 (v9.1 개정 Blueprint)",type="primary",
                 use_container_width=True,disabled=(not GEMINI_KEY or not img_brand or not img_features)):
        # 이미지 URL 자동 수집
        auto_img_url=img_image_url
        if not auto_img_url and st.session_state.get("live_results"):
            live_imgs=[r.get("image_url","") for r in st.session_state["live_results"] if r.get("image_url","").startswith("http")]
            if live_imgs: auto_img_url=live_imgs[0]

        with st.spinner("v9.1 Blueprint 기준 DALL-E 3 프롬프트 설계 중... (20~40초)"):
            result=generate_image_prompts_v91(img_brand,img_url,auto_img_url,img_features,img_target,img_category)
        st.session_state["img_prompt"]=result
    st.markdown('</div>',unsafe_allow_html=True)

    if st.session_state.get("img_prompt"):
        st.markdown("---")
        st.markdown("**🎨 12개 이미지 프롬프트 (DALL-E 3 최적화 | 상단 40% 솔리드 배경)**")
        st.caption("DALL-E 3 Prompt 텍스트를 복사 → ChatGPT에 '이 프롬프트로 이미지를 생성해줘:' 와 함께 붙여넣기")

        prompt_text=st.session_state["img_prompt"]
        image_blocks=_re.split(r"\[Image\s*(\d+)",prompt_text)

        if len(image_blocks)>1:
            idx=1
            while idx<len(image_blocks):
                num=image_blocks[idx]
                content=image_blocks[idx+1] if idx+1<len(image_blocks) else ""
                first_line=content.split("\n")[0].strip().strip(":").strip("]").strip()
                spec=[s for s in IMAGE_SPEC if s["no"]==int(num)] if num.isdigit() else []
                size_info=f" | 860×{spec[0]['h']}px" if spec else ""
                with st.expander(f"🖼 Image {num}: {first_line}{size_info}", expanded=False):
                    st.markdown(content)
                    dalle_match=_re.search(r"DALL-E 3 Prompt:\s*\n?(Photorealistic[^\[]+)",content,_re.I|_re.S)
                    if dalle_match:
                        dalle_prompt=dalle_match.group(1).strip()
                        st.markdown("**📋 ChatGPT 붙여넣기용:**")
                        full_gpt=f"이 프롬프트로 이미지를 생성해줘:\n\n{dalle_prompt}"
                        st.code(full_gpt,language=None)
                        # ★ 복사 버튼
                        components.html(copy_button_html(full_gpt,f"📋 Image {num} 복사"),height=44)
                        st.download_button(f"💾 저장",data=full_gpt,
                                           file_name=f"{img_brand}_{num.zfill(2)}.txt",
                                           mime="text/plain",key=f"img_dl_{num}")
                idx+=2
        else:
            st.markdown(prompt_text)

        st.markdown("<br>",unsafe_allow_html=True)
        download_text=build_download_text(img_brand if img_brand else "상품",prompt_text)
        dl_c,_img_tg_col,clr_c=st.columns([2,1.5,1])
        with dl_c:
            st.download_button("💾 전체 12개 TXT 다운로드",data=download_text,
                file_name=f"{img_brand if img_brand else '상품'}_상세페이지_v91.txt",
                mime="text/plain",use_container_width=True)
        _img_tg_ph=st.empty()
        with _img_tg_col:
            if st.button("📱 텔레그램 전송",use_container_width=True,key="img_tg"):
                ok_sent=send_tg_long(prompt_text,"🎨 상세페이지 프롬프트 v9.1")
                if ok_sent: _img_tg_ph.success("✅ 전송 완료")
                else: _img_tg_ph.error("❌ 전송 실패")
        with clr_c:
            if st.button("초기화",use_container_width=True,key="img_clr"):
                st.session_state["img_prompt"]=None; st.rerun()

        st.info("💡 ChatGPT 사용법: 각 Image의 '📋 복사' 버튼 → ChatGPT(GPT-4o) 대화창 붙여넣기 → Enter\n"
                "무료 계정: 하루 일정 횟수 | Plus($20/월): 제한 없음")

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
본인 chat.id: 8402196636
친구 chat.id: 922742140

친구에게 전송 조건: 친구가 먼저 봇에게 /start 메시지 전송 필요 (완료됨)
        """)
    with col_b:
        st.markdown("Secrets 등록")
        st.code("""DOMEGGOOK_API_KEY  = "API키"
TELEGRAM_BOT_TOKEN = "봇토큰"
TELEGRAM_CHAT_IDS  = "8402196636,922742140"
GEMINI_API_KEY     = "제미나이키(무료)"
""",language="toml")
        st.info("💡 TELEGRAM_CHAT_ID 대신 TELEGRAM_CHAT_IDS를 사용하면 두 사람 모두에게 전송됩니다.")
        _t5_ph=st.empty()
        test_msg=st.text_input("테스트 메시지",value="소싱레이더 연동 테스트")
        if st.button("테스트 발송",type="primary",use_container_width=True):
            ok=send_telegram_message(test_msg)
            if ok: _t5_ph.success("✅ 성공 (등록된 모든 수신자에게 발송)")
            else: _t5_ph.error("❌ 실패")

# ══════════════════════════════════════════════════════════════
# TAB 6: 가이드
# ══════════════════════════════════════════════════════════════
with tab6:
    st.markdown("### 📖 가이드")
    with st.expander("업체등급 — 왜 처음에 안 나오나요?"):
        st.markdown("""
도매매/도매꾹 목록 API(getItemList)는 seller/grade 필드를 반환하지 않습니다.
상세 API(getItemView)에서만 등급 정보가 제공됩니다.

등급 확인 3가지 방법:
1. 🏅 업체등급 조회 버튼 — 검색 결과 상위 15개를 상세 API로 일괄 조회 (5~10초)
2. ⭐ 관심 등록 — 관심 등록 즉시 해당 상품 상세 API 호출 → 등급 영구 저장
3. 등급은 session_state에 캐시되어 재검색 없이도 유지됩니다

Streamlit 로그(Manage app → Logs)에서 [상세 seller원문] 줄을 확인하면
실제 API가 반환하는 등급 필드명을 알 수 있습니다.
        """)
    with st.expander("온채널 — 왜 검색이 안 되나요?"):
        st.markdown("""
확인 결과: www.onch3.co.kr은 모든 클라우드 서버 IP에 대해 HTTP 403을 반환합니다.
로그인 요청조차 거부되므로 크롤링이 구조적으로 불가능합니다.

해결 방법:
방법 1. 로컬 PC에 Python + Streamlit 설치 후 직접 실행 (일반 IP로 접속 가능)
방법 2. 온채널 API 계약 문의 (기업 계정 기준)
방법 3. 온채널 사이트를 직접 방문하여 상품 확인

도매매/도매꾹은 정상 동작합니다.
        """)
    with st.expander("키워드 복사 사용법"):
        st.markdown("""
📋 복사 버튼 클릭 → 클립보드에 자동 복사 → 어디서든 Ctrl+V 붙여넣기

복사 형식: 키워드1, 키워드2, 키워드3 (쉼표 구분)
네이버 스마트스토어 상품 등록 태그 입력창에 그대로 붙여넣기 가능합니다.
        """)
    with st.expander("AI 이미지 v9.1 — 점수 개선 내용"):
        st.markdown("""
전환율 65→85 개선:
가격 앵커 시각 요소, 한정성 강조, 수치 기반 혜택 (XX% 절감, 하루 1개 등)

법적 안전성 55→80 개선:
가짜 리뷰 수치 금지, 미검증 인증마크 금지, 의학적 효능 과장 금지
사용자가 제공한 실측 데이터만 사용

스마트스토어 실전성 70→90 개선:
모바일 우선 설계, 단일 초점 레이아웃, 수직 스크롤 최적화
높은 대비 배경/전경, 콜라주 금지
        """)
    with st.expander("플랫폼별 수수료"):
        st.markdown("""
| 플랫폼 | 수수료 | 비고 |
|---|---|---|
| 네이버 스마트스토어 | 6% | 판매2.73%+결제3.3% |
| 쿠팡 | 11% | 4~10.8% 카테고리별 |
| 11번가 | 12% | 6~13% 카테고리별 |
| G마켓 | 12% | 4~15% 카테고리별 |
| 옥션 | 12% | G마켓 동일 구조 |
        """)
