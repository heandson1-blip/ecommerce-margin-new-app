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
.kw-card{background:white;border:1px solid #e2e8f0;border-radius:10px;padding:1rem 1.2rem;margin-bottom:.75rem}
.kw-chip{display:inline-block;background:#EFF6FF;color:#1D4ED8;font-size:.78rem;
    padding:3px 10px;border-radius:20px;margin:2px;font-weight:500}
.ai-section{background:white;border-radius:12px;padding:1.2rem 1.4rem;
    border:1px solid #e2e8f0;margin-bottom:1rem}
.copy-row{display:flex;align-items:center;gap:8px;margin:.3rem 0}
.copy-row b{min-width:90px;font-size:.85rem;color:#374151}
.copy-chip-wrap{flex:1;display:flex;flex-wrap:wrap;gap:4px}
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
    "네이버 스마트스토어":0.06,
    "쿠팡":0.11,
    "11번가":0.12,
    "G마켓":0.12,
    "옥션":0.12,
}
MARGIN_MAP={"안정형  (10%)":0.10,"밸런스형 (20%)":0.20,"고마진형 (40%)":0.40}
FETCH_PRESETS={"빠른 탐색  (50개)":(50,1),"일반 검색  (100개)":(50,2),
               "심층 분석  (200개)":(50,4),"대량 수집  (500개)":(50,10)}
PLATFORM_KW_GUIDE={
    "네이버 스마트스토어":{"format":"브랜드+상품유형+핵심특징+타겟/용도","max_len":100,"max_kw":10,
        "tip":"네이버 쇼핑 알고리즘은 정확한 상품명+핵심 키워드 조합을 선호. 브랜드명+상품유형+특징 순서 유지"},
    "쿠팡":{"format":"핵심상품명+용량/수량+주요특징","max_len":50,"max_kw":8,
        "tip":"상품명 간결하게, 검색태그에 롱테일 키워드 분산. 리뷰수와 배송속도가 노출에 영향"},
    "11번가":{"format":"브랜드+상품명+모델명/규격+수량","max_len":80,"max_kw":10,
        "tip":"가격 경쟁력과 함께 상세한 상품명 효과적. SK페이 할인 연동 상품 유리"},
    "G마켓":{"format":"브랜드+상품유형+특징+구성/용량","max_len":80,"max_kw":10,
        "tip":"카테고리 최적화 중요. 스마일클럽 회원 대상 키워드 포함 시 노출 유리"},
    "옥션":{"format":"브랜드+상품유형+구성수량+할인/혜택","max_len":80,"max_kw":10,
        "tip":"기획전/딜 노출 중요. 가격 경쟁력 강조 키워드와 묶음할인 구성 효과적"},
}

# PDF 가이드 이미지 구성 (가이드북 v2.0 기준)
IMAGE_GUIDE = [
    {"no":1,"section":"HOOK","purpose":"3초 안에 시선 확보","height":"1800~2400px",
     "prompt":"Photorealistic, commercial photography, hero shot of [제품명], premium lifestyle scene, attractive target customer model, clean white background, natural lighting, product centered, modern ecommerce design, realistic texture, high detail, 860px width, 2200px height"},
    {"no":2,"section":"문제 공감","purpose":"고객의 현실 문제 자극","height":"1500~2000px",
     "prompt":"Photorealistic split scene showing customer problem situation, emotional expression, relatable daily life context, product not yet introduced, clean commercial photography, natural lighting, ecommerce storytelling, 860px width, 1800px height"},
    {"no":3,"section":"해결 제안","purpose":"제품 등장 Before/After","height":"1700~2200px",
     "prompt":"Photorealistic before and after comparison, customer before experiencing problem and after using product, visible positive transformation, premium ecommerce design, natural lighting, 860px width, 2000px height"},
    {"no":4,"section":"핵심 가치 1","purpose":"가장 강력한 USP","height":"1600~2200px",
     "prompt":"Photorealistic close-up of product feature, visual emphasis on key benefit, premium commercial photography, minimal background, natural lighting, ecommerce infographic style, 860px width, 1800px height"},
    {"no":5,"section":"핵심 가치 2","purpose":"두 번째 구매 이유","height":"1600~2200px",
     "prompt":"Photorealistic benefit-focused product scene, lifestyle application, realistic usage context, clean ecommerce design, natural lighting, 860px width, 1800px height"},
    {"no":6,"section":"핵심 가치 3","purpose":"세 번째 구매 이유","height":"1600~2200px",
     "prompt":"Photorealistic macro detail showing product texture, material, ingredient, function or quality, premium commercial photography, natural lighting, 860px width, 1800px height"},
    {"no":7,"section":"핵심 가치 4","purpose":"경쟁제품 차별화","height":"1600~2200px",
     "prompt":"Photorealistic comparison concept without competitor branding, highlighting superior product advantage, clean ecommerce layout, natural lighting, 860px width, 1800px height"},
    {"no":8,"section":"핵심 가치 5","purpose":"사용 편의성/감성 가치","height":"1600~2200px",
     "prompt":"Photorealistic lifestyle scene showing convenient use of product in daily life, emotional satisfaction, clean premium commercial photography, 860px width, 1800px height"},
    {"no":9,"section":"신뢰 구간","purpose":"구매 의심 제거","height":"2000~3000px",
     "prompt":"Photorealistic trust-building ecommerce section, customer review cards, certification placeholders, premium quality presentation, clean infographic layout, commercial photography, 860px width, 2600px height"},
    {"no":10,"section":"상세 정보","purpose":"구매 판단 완료","height":"2200~3000px",
     "prompt":"Photorealistic product specification table, clean infographic design, icons and structured information blocks, ecommerce detail page style, modern layout, 860px width, 2800px height"},
    {"no":11,"section":"구매 전 체크","purpose":"반품 감소 / 구매 확신","height":"1500~1800px",
     "prompt":"Photorealistic recommendation guide section, customer personas, icon-based information layout, modern ecommerce design, clean white background, natural lighting, 860px width, 1700px height"},
    {"no":12,"section":"CTA","purpose":"최종 구매 유도","height":"1500~2000px",
     "prompt":"Photorealistic premium hero product shot, strong purchase motivation, product prominently displayed, elegant ecommerce call-to-action design, natural lighting, clean background, high conversion layout, 860px width, 1800px height"},
]

for k,v in {"live_results":[],"show_results":False,"search_error":None,
            "page_num":0,"ai_result":None,
            "live_view":"card","mon_view":"card",   # ★ 카드가 기본값
            "kw_result":None,"img_prompt":None,
            "card_ai_selected":set()}.items():
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
            errors.append("온채널 ID/PW 미설정")
        elif kw:
            try:
                oc=oc_client.fetch_product_list(keyword=kw,page_size=pg_size*max_pg,max_pages=max_pg)
                results.extend(oc)
            except Exception as e:
                errors.append(str(e))

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
    """도매매/도매꾹 상품 페이지 URL 생성"""
    site=row.get("site","")
    pid=str(row.get("product_id",""))
    if site=="도매꾹":
        return f"https://domeggook.com/main/item/itemView.php?no={pid}"
    elif site=="도매매":
        return f"https://domeggook.com/main/item/itemView.php?no={pid}&market=supply"
    elif pid.startswith("OC_"):
        return f"https://www.onch3.co.kr/goods_view.php?vnum={pid[3:]}"
    return ""

def render_cards(df, tracked_ids, id_prefix, on_toggle,
                 show_ai_select=False, ai_selected_set=None):
    """공통 카드 그리드 — 클릭 시 상품 페이지 링크, AI선택 체크박스 포함"""
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

                # 이미지 (클릭 → 상품 링크)
                if img and img.startswith("http"):
                    if prod_url:
                        st.markdown(
                            f'<a href="{prod_url}" target="_blank">'
                            f'<img src="{img}" style="width:100%;border-radius:8px;'
                            f'cursor:pointer;margin-bottom:6px" /></a>',
                            unsafe_allow_html=True)
                    else:
                        try: st.image(img,width=220)
                        except: st.markdown("📦")
                else:
                    if prod_url:
                        st.markdown(
                            f'<a href="{prod_url}" target="_blank" style="text-decoration:none">'
                            f'<div style="height:90px;background:#f1f5f9;border-radius:8px;'
                            f'display:flex;align-items:center;justify-content:center;'
                            f'font-size:2.5rem;margin-bottom:6px;cursor:pointer">📦</div></a>',
                            unsafe_allow_html=True)
                    else:
                        st.markdown("<div style='height:90px;background:#f1f5f9;border-radius:8px;"
                                    "display:flex;align-items:center;justify-content:center;"
                                    "font-size:2.5rem;margin-bottom:6px'>📦</div>",unsafe_allow_html=True)

                gc={"S":"#f59e0b","A":"#3b82f6","B":"#22c55e","C":"#eab308",
                    "D":"#f97316","E":"#ef4444"}.get(
                    grade[0].upper() if grade and grade[0].isalpha() else "","#94a3b8")

                name_link=(f'<a href="{prod_url}" target="_blank" style="color:#1e293b;'
                           f'text-decoration:none">{row["name"][:30]}</a>'
                           if prod_url else row["name"][:30])

                st.markdown(f"""
<div style="font-size:.82rem;font-weight:500;white-space:nowrap;overflow:hidden;
    text-overflow:ellipsis;margin-bottom:3px" title="{row['name']}">{name_link}</div>
<div style="font-size:.7rem;color:#94a3b8;margin-bottom:3px">
    {row.get('site','')} | {row.get('product_id','')}</div>
<div style="font-size:.75rem;color:#475569;margin-bottom:2px">
    공급가 <b>{int(row['supply_price']):,}원</b> 배송비 <b>{int(row['delivery_fee']):,}원</b></div>
<div style="font-size:.9rem;font-weight:700;color:#2563eb;margin-bottom:2px">
    판매가 {sale:,}원 &nbsp; 순수익 {profit:,}원</div>
<div style="font-size:.72rem;color:#64748b">
    마진 <b>{mp:.1f}%</b> &nbsp;|&nbsp;
    등급 <span style="color:{gc};font-weight:600">{grade if grade else '조회 필요'}</span> &nbsp;|&nbsp;
    {row.get('상태','')}</div>""",unsafe_allow_html=True)

                # AI 선택 체크박스 (카드 보기에서도 가능)
                if show_ai_select and ai_selected_set is not None:
                    ai_checked = pid in ai_selected_set
                    new_checked = st.checkbox("🤖 AI 분석 선택",
                                              value=ai_checked,
                                              key=f"ai_card_{id_prefix}_{pid}")
                    if new_checked != ai_checked:
                        if new_checked:
                            ai_selected_set.add(pid)
                        else:
                            ai_selected_set.discard(pid)
                        st.session_state["card_ai_selected"] = ai_selected_set

                # 관심 등록 버튼
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
    except Exception as e:
        return f"AI 연결 오류: {e}"

def compact_ai(items_df,fee,margin,platform_name,margin_name):
    rows=[]
    for _,r in items_df.iterrows():
        profit=int(r.get("예상 순수익(원)",0))
        sale=int(r.get("추천 판매가(원)",0))
        supply=int(r.get("supply_price",0))
        deliv=int(r.get("delivery_fee",0))
        mp=float(r.get("마진율(%)",0))
        grade=r.get("seller_grade","미확인") or "미확인"
        rows.append(f"{r['name'][:28]} ({r.get('site','')})\n"
                    f"  원가{supply+deliv:,}원 판매가{sale:,}원 순수익{profit:,}원/건 마진{mp:.1f}% 등급{grade}")
    prompt=f"""이커머스 소싱 전문가로서 마케팅과 판매 관점에서 핵심만 분석하세요.
판매 설정: {platform_name} 수수료{int(fee*100)}% / 목표마진 {int(margin*100)}%

분석 상품:
{chr(10).join(rows)}

아래 형식으로만 출력하세요. 줄 앞에 대시(-), 해시(#), 별표(*) 없이 작성. 이모티콘 유지.

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
내용 2줄 이내

각 섹션 5줄 이내, 수치 포함, 간결하게."""
    return gemini_call(prompt,1800)

def generate_keywords(prod_name, features, platforms):
    guide_str="\n".join([
        f"[{p}] 형식={PLATFORM_KW_GUIDE[p]['format']}, 최대{PLATFORM_KW_GUIDE[p]['max_len']}자, 키워드{PLATFORM_KW_GUIDE[p]['max_kw']}개"
        for p in platforms
    ])
    prompt=f"""이커머스 SEO 전문가. 아래 상품의 플랫폼별 최적 키워드를 생성하세요.

상품명: {prod_name}
주요 특징: {features}

{guide_str}

각 플랫폼별 출력 형식 (## 없이, 이모티콘 유지):

[플랫폼명]
추천 상품명: (최적 상품명)
핵심 키워드: 키워드1, 키워드2, 키워드3, 키워드4, 키워드5
롱테일 키워드: 키워드1, 키워드2, 키워드3
태그: 태그1, 태그2, 태그3, 태그4, 태그5
등록 팁: 한줄

플랫폼 간 구분: ---"""
    return gemini_call(prompt,2000)

def fetch_url_content(url: str) -> str:
    """URL 내용 실제 fetch"""
    if not url or not url.startswith("http"):
        return ""
    try:
        from bs4 import BeautifulSoup
        resp=req.get(url, headers={"User-Agent":"Mozilla/5.0"}, timeout=10)
        if resp.status_code==200:
            resp.encoding=resp.apparent_encoding
            soup=BeautifulSoup(resp.text,"html.parser")
            # 스크립트/스타일 제거
            for tag in soup(["script","style","nav","footer","header"]):
                tag.decompose()
            text=soup.get_text(separator="\n",strip=True)
            # 최대 2000자
            return text[:2000]
    except Exception as e:
        print(f"[URL fetch 오류] {e}")
    return ""

def generate_image_prompts(brand, product_url, features, target):
    """PDF 가이드북 v2.0 기준 — 12개 이미지 프롬프트 생성"""
    # URL 실제 fetch
    url_content=""
    if product_url and product_url.startswith("http"):
        url_content=fetch_url_content(product_url)
        if url_content:
            url_content=f"\n참고 URL 내용:\n{url_content}"

    # 가이드북 이미지 구조 요약
    guide_summary="\n".join([
        f"이미지{g['no']} [{g['section']}] 목적:{g['purpose']} 높이:{g['height']}"
        for g in IMAGE_GUIDE
    ])

    prompt=f"""당신은 네이버 스마트스토어 상세페이지 전문 디자이너이자 퍼포먼스 마케터입니다.
아래 가이드북 규칙에 따라 12개 이미지 프롬프트를 설계하세요.

브랜드명: {brand}
타겟 고객: {target}
주요 특징: {features}{url_content}

가이드북 이미지 구성:
{guide_summary}

공통 디자인 규칙:
가로 860px 고정 / 배경: White or Light Gray / 스타일: Photorealistic, Commercial Photography, Natural Lighting, Clean Ecommerce Design / 폰트: 헤드라인 S-Core Dream Bold, 본문 Pretendard Regular

AI 자동 분석 항목 (먼저 분석 후 각 이미지에 반영):
타겟고객 / 고객문제 / 구매이유5가지 / 경쟁차별점 / 신뢰요소 / 구매트리거

출력 형식 (이모티콘 유지, 줄 앞 특수문자 없이):

[이미지 1: HOOK]
목적: 3초 안에 시선 확보
이미지 높이: 2200px
메인 카피: (고객이 얻는 가장 큰 결과 또는 호기심 유발 문장)
서브 카피: (설명 1~2문장)
보조 포인트: 포인트1 / 포인트2 / 포인트3
신뢰 요소: (1개)
image 2 프롬프트: Photorealistic, commercial photography, hero shot of {brand}, ...860px width, 2200px height

[이미지 N: 섹션명]
...

위 형식으로 이미지 1~12 모두 작성하세요. 한 이미지 = 하나의 설득 완결."""

    return gemini_call(prompt,4000)

def build_download_text(brand, prompts_text):
    """다운로드용 텍스트 구성"""
    return f"""소싱레이더 — AI 상세페이지 이미지 프롬프트
브랜드: {brand}
생성일: {datetime.now().strftime('%Y.%m.%d %H:%M')}
가이드: 범용 스마트스토어 상세페이지 Image 2 생성 프롬프트 제작 가이드북 v2.0

{'='*60}

{prompts_text}

{'='*60}
사용 방법:
1. 각 [이미지 N]의 'image 2 프롬프트' 부분을 복사
2. ChatGPT (GPT-4o with DALL-E) 또는 Adobe Firefly에 붙여넣기
3. 생성된 이미지를 860px 기준으로 다운로드
4. 스마트스토어 상세페이지에 순서대로 등록
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
            st.caption("온채널: ID/PW 등록됨 (클라우드 서버 차단으로 검색 불가)")
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
    c1,c2=st.columns(2); c1.metric("등록 상품",total_t); c2.metric("평균 순수익",f"{avg_p_t:,}원")
    st.markdown("---")
    st.markdown("#### 텔레그램")
    try: tg_ok=st.secrets.get("TELEGRAM_BOT_TOKEN","") not in ["","봇토큰_입력"]
    except: tg_ok=False
    st.markdown(f"상태: {'연동됨' if tg_ok else '미설정'}")
    if st.button("테스트 발송",use_container_width=True):
        ok=send_telegram_message(f"소싱레이더 연동 테스트\n관심상품 {total_t}개")
        st.success("완료") if ok else st.error("실패")
    st.markdown("---")
    st.markdown(f"#### AI (Gemini 무료)\n{'사용 가능' if GEMINI_KEY else 'GEMINI_API_KEY 미설정'}")
    st.markdown("---")
    st.caption("소싱레이더 v6.1")

# ── 헤더 ────────────────────────────────────────────────────
st.markdown("""<div class="main-header">
    <h1>📡 소싱레이더</h1>
    <p>도매매 도매꾹 실시간 통합 마진 분석 시스템</p>
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
            <div style="font-size:.8rem;margin-top:.3rem">
                업체등급: 🏅 등급 조회 버튼 클릭 또는 ⭐ 관심 등록 시 자동 갱신</div>
        </div>""",unsafe_allow_html=True)
    else:
        raw_df=pd.DataFrame(st.session_state["live_results"])
        if raw_df.empty:
            st.info("검색 결과가 없습니다.")
        else:
            for col,default in [("seller_grade",""),("image_url","")]:
                if col not in raw_df.columns: raw_df[col]=default

            # 업체등급 조회 버튼
            grade_missing=int((raw_df["seller_grade"]=="").sum()+(raw_df["seller_grade"].isna()).sum())
            if grade_missing>0 and client:
                col_gb,_=st.columns([2.5,3])
                with col_gb:
                    if st.button(f"🏅 업체등급 조회 (상위 15개 상세 조회, 약 5~10초)",
                                 use_container_width=True,type="secondary"):
                        with st.spinner("업체등급 조회 중... (도매매/도매꾹 상세 API 호출)"):
                            updated=client.batch_fetch_grades(raw_df.to_dict("records"),limit=15)
                            updated_df=pd.DataFrame(updated)
                            st.session_state["live_results"]=updated_df.to_dict("records")
                        st.success(f"등급 조회 완료! Streamlit 로그에서 [상세 seller원문]을 확인하면 실제 API 필드명을 알 수 있습니다.")
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
                        "업체등급":st.column_config.TextColumn("업체등급",help="🏅 등급 조회 버튼 또는 관심 등록 시 갱신"),
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
        total_m=len(tracked_df)
        t_calc=apply_margin(tracked_df,fee,margin)
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
            # ★ 카드 보기에서도 AI 선택 가능
            render_cards(mdf,tracked_ids_m,"mon",
                         lambda p,t:(upsert_tracked_product(p,t),st.rerun()),
                         show_ai_select=True,ai_selected_set=card_ai)
        else:
            mdf["AI선택"]=False; mdf["해제"]=True
            if "updated_at" in mdf.columns:
                mdf["등록일"]=mdf["updated_at"].apply(fmt_dt)
            keep=["AI선택","해제","site","product_id","name","supply_price","delivery_fee",
                  "상태","추천 판매가(원)","예상 순수익(원)","마진율(%)","seller_grade","등록일"]
            mdf_disp=mdf[[c for c in keep if c in mdf.columns]].copy()
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
            track_changed=False
            for i in range(len(edited_m)):
                if not edited_m.iloc[i]["해제"]:
                    upsert_tracked_product(mdf.iloc[i].to_dict(),0); track_changed=True
            if track_changed: st.rerun()

        st.markdown("<br>",unsafe_allow_html=True)
        tg_placeholder = st.empty()
        if st.button("📱 관심 상품 현황 텔레그램 전송",use_container_width=True):
            lines=[f"관심 상품 현황\n전체 {total_m}개 / 정상 {ok_m}개 / 평균마진 {avg_m:.1f}%\n"]
            for _,row in t_calc.iterrows():
                icon="O" if row["status"]=="Y" else "X"
                lines.append(f"{icon} {row['name'][:22]} 판매가{int(row['추천 판매가(원)']):,}원 수익{int(row['예상 순수익(원)']):,}원")
            ok_sent=send_tg_long("\n".join(lines),"관심 상품 현황")
            if ok_sent:
                tg_placeholder.success("✅ 전송 완료")
            else:
                tg_placeholder.error("❌ 전송 실패")

        # ── AI 소싱 분석 ──────────────────────────────────────
        st.markdown("---")
        st.markdown("#### 🤖 AI 소싱 분석")
        if not GEMINI_KEY:
            st.info("aistudio.google.com 에서 무료 키 발급 후 Secrets에 GEMINI_API_KEY 등록")
        else:
            # 선택 항목 수집 (카드/표 모두)
            sel_count=0; sel_df=pd.DataFrame()
            if st.session_state["mon_view"]=="card":
                # 카드뷰 AI 선택
                sel_pids=st.session_state.get("card_ai_selected",set())
                sel_count=len(sel_pids)
                if sel_count>0:
                    sel_df=t_calc[t_calc["product_id"].astype(str).isin(sel_pids)].copy()
                st.info(f"카드에서 🤖 AI 분석 선택: {sel_count}개")
            elif edited_m is not None and "AI선택" in edited_m.columns:
                sel_rows=edited_m[edited_m["AI선택"]==True]; sel_count=len(sel_rows)
                if sel_count>0:
                    sel_names=sel_rows["상품명"].tolist()
                    sel_df=t_calc[t_calc["name"].isin(sel_names)].copy()

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
                tg2,clr=st.columns([2,1])
                with tg2:
                    ai_tg_ph = st.empty()
                    if st.button("📱 분석 결과 텔레그램 전송",use_container_width=True,key="ai_tg"):
                        ok_sent=send_tg_long(result_text,"🤖 AI 소싱 분석")
                        if ok_sent:
                            ai_tg_ph.success("✅ 전송 완료")
                        else:
                            ai_tg_ph.error("❌ 전송 실패")
                with clr:
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
        live_names=[r["name"] for r in st.session_state["live_results"][:20]]
        sel_from_live=st.selectbox("또는 검색 결과에서 선택",["직접 입력"]+live_names,key="kw_from_live")
    if st.button("🔑 키워드 생성",type="primary",use_container_width=True,
                 disabled=(not GEMINI_KEY or not kw_prod or not kw_platforms)):
        with st.spinner("플랫폼별 키워드 생성 중..."):
            result=generate_keywords(kw_prod,kw_feat,kw_platforms)
        st.session_state["kw_result"]=result
    st.markdown('</div>',unsafe_allow_html=True)

    if st.session_state.get("kw_result"):
        st.markdown("---")
        st.markdown("**🔑 플랫폼별 키워드 결과**")
        result_text=st.session_state["kw_result"]

        # 결과 내 재검색
        kw_inner=st.text_input("결과 내 키워드 재검색","",
                               placeholder="키워드 입력 시 해당 내용 포함된 항목만 표시...",
                               key="kw_inner_filter")

        # 플랫폼 섹션 파싱
        sections=[s.strip() for s in result_text.split("---") if s.strip()]
        for section in sections:
            lines=[l.strip() for l in section.split("\n") if l.strip()]
            if not lines: continue
            header=lines[0].replace("##","").strip().strip("[]").strip()

            # 재검색 필터 적용
            if kw_inner and kw_inner.lower() not in section.lower():
                continue

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
                            # 칩 + 클립보드 복사 버튼 (텍스트 박스 없이)
                            copy_js = f"""
<div class="copy-row">
  <b>{label}:</b>
  <div class="copy-chip-wrap">{chips}</div>
  <button onclick="navigator.clipboard.writeText('{copy_text}').then(()=>{{
    this.textContent='✅';setTimeout(()=>this.textContent='📋',1500)}})"
    style="background:#3b82f6;color:white;border:none;border-radius:6px;
    padding:4px 10px;font-size:.8rem;cursor:pointer;flex-shrink:0">📋 복사</button>
</div>"""
                            st.markdown(copy_js, unsafe_allow_html=True)
                        else:
                            st.markdown(f"**{label}:** {content}")
                    else:
                        st.markdown(line)

        kw_tg_ph=st.empty()
        tg_kw,clr_kw=st.columns([2,1])
        with tg_kw:
            if st.button("📱 키워드 텔레그램 전송",use_container_width=True,key="kw_tg"):
                ok_sent=send_tg_long(result_text,"🔑 키워드 생성 결과")
                if ok_sent:
                    kw_tg_ph.success("✅ 전송 완료")
                else:
                    kw_tg_ph.error("❌ 전송 실패")
        with clr_kw:
            if st.button("초기화",use_container_width=True,key="kw_clr"):
                st.session_state["kw_result"]=None; st.rerun()

# ══════════════════════════════════════════════════════════════
# TAB 4: AI 이미지 생성
# ══════════════════════════════════════════════════════════════
with tab4:
    st.markdown("### 🎨 AI 상세페이지 이미지 프롬프트 생성")
    st.markdown("범용 스마트스토어 상세페이지 Image 2 생성 프롬프트 제작 가이드북 v2.0 기준으로 12개 이미지를 설계합니다.")

    with st.expander("📋 이미지 구성 미리보기 (가이드북 v2.0 기준)", expanded=False):
        for g in IMAGE_GUIDE:
            st.markdown(f"**이미지 {g['no']} [{g['section']}]** — {g['purpose']} | 높이: {g['height']}")

    st.markdown('<div class="ai-section">',unsafe_allow_html=True)
    img_col1,img_col2=st.columns(2)
    with img_col1:
        img_brand=st.text_input("브랜드명",placeholder="예: 인터뷰어 토마토즙",key="img_brand")
        img_target=st.text_input("타겟 고객",placeholder="예: 20~40대 건강관리에 관심있는 직장인",key="img_target")
        img_category=st.selectbox("상품 카테고리",
                                  ["식품/음료","뷰티/화장품","패션/의류","생활용품",
                                   "디지털/가전","스포츠/레저","반려동물","기타"],key="img_category")
    with img_col2:
        img_url=st.text_input("참고 상품 URL (선택 — 실제 페이지 내용 참조)",
                              placeholder="https://... 입력 시 AI가 실제 페이지 내용 분석",key="img_url")
        st.caption("톤앤매너는 AI가 타겟/카테고리 기반으로 자동 결정합니다.")

    img_features=st.text_area("상품 주요 특징 (상세히 입력할수록 좋습니다)",
        placeholder="1. 국산 토마토 100% 사용\n2. NFC 착즙 방식\n3. 무첨가 원칙 ...",
        height=150,key="img_features")

    if st.button("🎨 12개 이미지 프롬프트 생성",type="primary",use_container_width=True,
                 disabled=(not GEMINI_KEY or not img_brand or not img_features)):
        if not GEMINI_KEY: st.error("GEMINI_API_KEY 필요")
        else:
            with st.spinner("가이드북 v2.0 기준으로 12개 이미지 프롬프트 설계 중... (20~40초)"):
                result=generate_image_prompts(img_brand,img_url,img_features,img_target)
            st.session_state["img_prompt"]=result
    st.markdown('</div>',unsafe_allow_html=True)

    if st.session_state.get("img_prompt"):
        st.markdown("---")
        st.markdown("**🎨 12개 이미지 프롬프트 — ChatGPT Image 2에 그대로 붙여넣기 가능**")
        prompt_text=st.session_state["img_prompt"]

        # 이미지별 expander
        import re as _re
        image_blocks=_re.split(r"\[이미지\s*(\d+)", prompt_text)
        if len(image_blocks)>1:
            i=1
            while i<len(image_blocks):
                num=image_blocks[i]
                content=image_blocks[i+1] if i+1<len(image_blocks) else ""
                section_line=content.split("\n")[0].strip().strip(":").strip("]").strip()
                with st.expander(f"🖼 이미지 {num}: {section_line}", expanded=False):
                    st.markdown(content)
                    # image 2 프롬프트만 추출해서 코드블록
                    eng_match=_re.search(r"image 2 프롬프트:\s*(Photorealistic[^\n]+(?:\n[^\[\n][^\n]+)*)",content,_re.I)
                    if eng_match:
                        eng_prompt=eng_match.group(1).strip()
                        st.markdown("**복사용 프롬프트:**")
                        st.code(eng_prompt,language=None)
                i+=2
        else:
            st.markdown(prompt_text)

        st.markdown("<br>",unsafe_allow_html=True)

        # 다운로드
        download_text=build_download_text(img_brand if img_brand else "상품", prompt_text)
        dl1,tg_img,clr_img=st.columns([2,1.5,1])
        with dl1:
            st.download_button(
                "💾 전체 프롬프트 TXT 다운로드",
                data=download_text,
                file_name=f"{img_brand if img_brand else '상품'}_상세페이지_프롬프트.txt",
                mime="text/plain",
                use_container_width=True
            )
        with tg_img:
            if st.button("📱 텔레그램 전송",use_container_width=True,key="img_tg"):
                ok_sent=send_tg_long(prompt_text,"🎨 상세페이지 이미지 프롬프트")
                st.success("전송 완료") if ok_sent else st.error("전송 실패")
        with clr_img:
            if st.button("초기화",use_container_width=True,key="img_clr"):
                st.session_state["img_prompt"]=None; st.rerun()

        st.info("💡 생성된 'image 2 프롬프트' 텍스트를 ChatGPT (GPT-4o)에 붙여넣으면 이미지가 생성됩니다. "
                "ChatGPT Plus(월 $20) 또는 무료 한도 내에서 사용 가능합니다.")

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
chat.id 뒤 숫자가 채팅방 ID
        """)
    with col_b:
        st.markdown("Secrets 등록")
        st.code("""DOMEGGOOK_API_KEY  = "API키"
TELEGRAM_BOT_TOKEN = "봇토큰"
TELEGRAM_CHAT_ID   = "내 채팅방ID"
TELEGRAM_CHAT_IDS  = "ID1,ID2,ID3"
GEMINI_API_KEY     = "제미나이키(무료)"
""",language="toml")
        test_msg=st.text_input("테스트 메시지",value="소싱레이더 연동 테스트")
        if st.button("테스트 발송",type="primary",use_container_width=True):
            ok=send_telegram_message(test_msg)
            st.success("성공") if ok else st.error("실패")

# ══════════════════════════════════════════════════════════════
# TAB 6: 가이드
# ══════════════════════════════════════════════════════════════
with tab6:
    st.markdown("### 📖 가이드")
    with st.expander("플랫폼별 수수료 안내 (2025년 기준)"):
        st.markdown("""
| 플랫폼 | 적용 수수료 | 실제 범위 |
|---|---|---|
| 네이버 스마트스토어 | 6% | 판매2.73%+결제3.3% |
| 쿠팡 | 11% | 4~10.8% 카테고리별 |
| 11번가 | 12% | 6~13% 카테고리별 |
| G마켓 | 12% | 4~15% 카테고리별 |
| 옥션 | 12% | 4~15% 카테고리별 |
        """)
    with st.expander("업체등급 — 왜 안 나오나요?"):
        st.markdown("""
도매매/도매꾹 목록 API에는 seller/grade 필드가 없습니다.

등급 확인 방법:
1. 검색 결과 상단 🏅 업체등급 조회 버튼 클릭 (상위 15개 상세 API 호출)
2. ⭐ 관심 등록 시 해당 상품 상세 API 즉시 호출 → 등급 자동 저장

Streamlit Cloud 로그(Manage app → Logs)에서 [상세 seller원문] 줄을 보면 
실제 API가 어떤 필드명으로 등급을 반환하는지 확인할 수 있습니다.
이 정보를 공유해주시면 정확하게 파싱하도록 코드를 수정할 수 있습니다.
        """)
    with st.expander("온채널 — 왜 검색이 안 되나요?"):
        st.markdown("""
온채널(onch3.co.kr)은 클라우드 서버 IP에 대해 403 차단을 적용합니다.
로그인 요청조차 403으로 거부됩니다.

해결 방법:
로컬 PC에 Python + Streamlit 설치 후 직접 실행하면 일반 IP로 접속되어 크롤링 가능합니다.
클라우드 배포 환경에서는 온채널 검색이 구조적으로 불가능합니다.
        """)
    with st.expander("AI 이미지 생성 — ChatGPT 사용 방법"):
        st.markdown("""
ChatGPT Image 2 사용 방법:
1. chatgpt.com 접속 (무료 계정 또는 Plus)
2. 소싱레이더에서 생성된 프롬프트 복사
3. ChatGPT 대화창에 붙여넣기
4. 생성된 이미지 우클릭 → 이미지 저장

무료 계정: 하루 일정 횟수 이미지 생성 가능
Plus($20/월): 제한 없이 생성 가능

Adobe Firefly (무료): firefly.adobe.com
Bing Image Creator (무료): bing.com/create
        """)
    with st.expander("마진 계산 공식"):
        st.markdown("""
추천 판매가 = (공급가 + 배송비) 나누기 (1 빼기 수수료율 빼기 마진율)
예상 순수익 = 판매가 빼기 (판매가 곱하기 수수료율) 빼기 공급가 빼기 배송비
        """)
