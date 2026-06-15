# 소싱레이더 (ecommerce-margin-new-app) — 개발 지침서 v2.0
# 작성일: 2026.06.15 | GitHub: heandson1-blip/ecommerce-margin-new-app

---

## ■ 프로젝트 개요

도매매·도매꾹 실시간 통합 마진 분석 → 소싱 의사결정 지원 → AI 상세페이지 생성 → 판매 플랫폼 자동 등록까지 이어지는 완전 관리형 이커머스 자동화 시스템.

---

## ■ 기술 스택 및 배포

- **런타임**: Python 3.12 / Streamlit >= 1.32
- **배포**: Streamlit Cloud (heandson1-blip/ecommerce-margin-new-app)
- **DB**: SQLite (sourcing.db) — 로컬 파일, 배포 환경에서 휘발성
- **AI**: Google Gemini 2.5 Flash Lite (무료, GEMINI_API_KEY)
- **알림**: Telegram Bot API (다중 수신자: TELEGRAM_CHAT_IDS)
- **이미지 생성**: Gemini로 DALL-E 3 프롬프트 생성 → ChatGPT(GPT-4o)에서 수동 생성

---

## ■ 현재 구현된 파일 구조

```
app.py              — 메인 Streamlit 앱 (6탭 구성)
domeme_client.py    — 도매매/도매꾹 API 클라이언트
database.py         — SQLite DB 초기화 및 CRUD
utils.py            — 마진 계산 유틸
notifications.py    — 텔레그램 다중 수신자 지원
main.py             — 일일 배치 (새벽 4시, 가격/재고 변동 감지)
requirements.txt    — 패키지 목록
```

**삭제된 파일**:
- `onchannel_client.py` — 온채널 클라우드 IP 403 차단으로 완전 제거
- `adapters.py`, `base_adapter.py` — 현재 미사용

---

## ■ Secrets 설정 (Streamlit Cloud)

```toml
DOMEGGOOK_API_KEY  = "도매꾹 API 키"
TELEGRAM_BOT_TOKEN = "봇 토큰"
TELEGRAM_CHAT_IDS  = "내ID,친구ID"   # 콤마 구분, 복수 수신자
GEMINI_API_KEY     = "Google AI Studio 무료 키"
```

---

## ■ 탭 구성 및 기능 현황

### TAB 1 — 🔍 라이브 검색

**현재 동작:**
- 도매매/도매꾹 API로 상품 목록 조회
- 카드 보기(기본) / 표 보기 전환
- 카드: 이미지 클릭 → 상품 상세 페이지 링크
- 필터: 재검색, 소싱처, 상태, 정렬

**업체등급 정책 (확정):**
- 목록 API(getItemList)는 seller/grade 필드 미제공 — 구조적 한계
- **🏅 업체등급 조회 버튼 삭제** (skill.md 요청 반영)
- 대신: ⭐ 관심 등록 시 상세 API(getItemView) 자동 호출 → 등급 DB 저장 + 세션 캐시
- 관심 등록 후 관심 상품 탭에서 등급 확인

**FETCH_PRESETS (단순 수량 분류, 이름만 다름):**
```python
{"빠른 탐색  (50개)": (50,1),
 "일반 검색  (100개)": (50,2),
 "심층 분석  (200개)": (50,4),
 "대량 수집  (500개)": (50,10)}
```

### TAB 2 — ⭐ 관심 상품

**현재 동작:**
- 관심 등록된 상품 목록 (카드/표 보기)
- KPI: 전체 / 정상 판매 / 평균 마진율 / 월 예상수익(100건)
- AI 소싱 분석: 선택 상품 또는 전체 분석 → 텔레그램 전송
- 관심 등록 시 즉시 상세 API 호출 → 배송비·등급·이미지 실제값 저장
- 일일 배치(main.py): 가격/재고 변동 감지 → 텔레그램 알림

### TAB 3 — 🔑 키워드 생성

**현재 동작:**
- 상품명 + 주요 특징 입력
- 네이버 쇼핑 자동완성 API + 쿠팡 자동완성 API로 실시간 인기 검색어 수집
- Gemini로 플랫폼별 최적 키워드 생성 (핵심/롱테일/태그/트렌드)
- 📋 복사 버튼 (execCommand 방식)

**삭제된 기능:**
- "검색 결과에서 선택" — 삭제됨
- 참고 상품 URL 기반 키워드 생성 — 미구현 (향후 검토)

**플랫폼 선택 문구**: "등록할 플랫폼" → "플랫폼 선택" (수정 필요)

### TAB 4 — 🎨 AI 이미지 생성

**현재 동작:**
- Blueprint v9.1 기준 12개 이미지 DALL-E 3 프롬프트 생성
- 이미지를 1개씩 순차 생성 (Gemini 429 방지, 요청 간 4초 대기)
- 상품 이미지 업로드 → Gemini Vision 분석 → 프롬프트에 패키지 정보 반영
- 생성된 프롬프트를 ChatGPT(GPT-4o)에 붙여넣어 이미지 생성

**확인된 문제 (수정 필요):**
- Vision 오류 503: Gemini Vision API 간헐적 서버 오류 → 텍스트 fallback 처리
- 토큰 부족: 카피+영문프롬프트가 800토큰 초과 → 구조 분리 필요
- DALL-E 3 영문 프롬프트가 잘리거나 누락되는 현상 → 프롬프트 구조 개선
- 생성된 프롬프트 내용이 너무 부실해 ChatGPT에서 이미지 생성 품질 낮음

**삭제된 기능:**
- 참고 상품 URL 크롤링 → 이미지 참조 (DALL-E 3 구조상 URL 이미지 참조 불가)
- 상품 이미지 URL 직접 입력 → 이미지 파일 업로드로 대체

**Blueprint v9.1 이미지 규격 (고정):**
```
01 HOOK          860×2200px
02 Painpoint     860×1800px
03 Solution      860×2000px
04 USP1          860×1800px
05 USP2          860×1800px
06 USP3          860×1800px
07 USP4          860×1800px
08 TPO           860×1800px
09 Certification 860×2500px
10 SpecsInfo     860×2800px
11 Audience      860×1600px
12 CTA           860×1800px
```

### TAB 5 — 📱 텔레그램 설정

- TELEGRAM_CHAT_IDS로 다중 수신자 지원
- 봇 토큰 발급, 채팅방 ID 확인 가이드
- 친구가 봇에 /start 전송 후 getUpdates로 ID 확인

### TAB 6 — 📖 가이드

---

## ■ 수수료 설정 (2025년 기준)

```python
PLATFORM_FEE = {
    "네이버 스마트스토어": 0.06,  # 판매2.73%+결제3.3%
    "쿠팡":               0.11,  # 카테고리 평균
    "11번가":             0.12,
    "G마켓":              0.12,
    "옥션":               0.12,
}
```

마진 계산식:
```
추천 판매가 = (공급가 + 배송비) / (1 - 수수료율 - 목표마진율)
예상 순수익 = 판매가 - (판매가 × 수수료율) - 공급가 - 배송비
```

---

## ■ 확정된 기술적 결론

| 항목 | 결론 |
|---|---|
| 온채널 연동 | ❌ 불가 (클라우드 서버 IP 403 차단) |
| 목록 API 업체등급 | ❌ 미제공 (상세 API에서만 가능) |
| 🏅 등급 조회 버튼 | ❌ 삭제 (관심 등록 시 자동 조회로 대체) |
| URL 이미지 참조 | ❌ 불가 (DALL-E 3 구조 한계) |
| 이미지 생성 | ✅ Gemini 프롬프트 → ChatGPT 수동 생성 |
| 텔레그램 다중 수신 | ✅ TELEGRAM_CHAT_IDS |
| 키워드 실시간 트렌드 | ✅ 네이버/쿠팡 자동완성 API |

---

## ■ 향후 개발 로드맵 (우선순위 순)

### Phase 1 — 현재 기능 안정화 (진행 중)
- [ ] AI 이미지 프롬프트 품질 개선 (DALL-E 3 영문 프롬프트 완성도)
- [ ] 업체등급 조회 버튼 삭제 + 관심 등록 시 자동 조회 안내 개선
- [ ] 키워드 탭 "플랫폼 선택" 문구 수정
- [ ] Gemini Vision 503 오류 fallback 강화

### Phase 2 — 데이터 분석 고도화
- [ ] 네이버 API 연동 (Client ID/Secret 발급 후)
  - 검색 API (블로그, 뉴스, 쇼핑)
  - 데이터랩 API (검색어 트렌드, 쇼핑인사이트)
  - 참고: https://d6wywma5jqtekhpq4cnfof.streamlit.app
- [ ] 쿠팡 파트너스 API 검토 (쿠팡은 공개 API 제한적 — 크롤링 검토)

### Phase 3 — 판매 플랫폼 자동 등록
- [ ] 네이버 스마트스토어 자동 상품 등록
- [ ] 쿠팡 Wing API 자동 상품 등록
- [ ] 이미지 자동 업로드 포함

### Phase 4 — 주문 자동화
- [ ] 송장 처리 자동화 (택배사별 API)
- [ ] 일괄 송장 처리 (일 1회 정해진 시간)
- [ ] Google Sheets 연동 (daily 데이터 관리)

### Phase 5 — CS 자동화
- [ ] 스마트스토어 리뷰 GEO 댓글 자동화
  - 참고: https://github.com/imteacherdana-sys/smartstore-review-geo-skill

---

## ■ AI 이미지 생성 — 올바른 사용법 (ChatGPT)

1. 소싱레이더에서 DALL-E 3 프롬프트 생성 (Gemini 무료)
2. "📋 복사" 버튼으로 클립보드 복사
3. chatgpt.com → GPT-4o 선택
4. 복사한 내용 붙여넣기 → Enter
5. 생성된 이미지 우클릭 → 이미지 저장
6. 파일명: {브랜드}_01_HOOK.png ... {브랜드}_12_CTA.png 순서로 저장
7. 스마트스토어 상세페이지에 01~12 순서로 등록

ChatGPT 무료: 하루 일정 횟수 제한
ChatGPT Plus ($20/월): 무제한

---

## ■ 주요 참고 링크

- 네이버 API: https://d6wywma5jqtekhpq4cnfof.streamlit.app
- 스마트스토어 리뷰: https://github.com/imteacherdana-sys/smartstore-review-geo-skill
- 나버 검색 참고: https://github.com/corazzon/st_naversearch
- MCP soloseller: https://lobehub.com/mcp/hbin77-mcp-soloseller
