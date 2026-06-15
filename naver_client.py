"""
naver_client.py — 네이버 API 클라이언트
- 검색 API: 쇼핑, 블로그, 뉴스
- 데이터랩 API: 검색어 트렌드, 쇼핑인사이트
Secrets: NAVER_CLIENT_ID, NAVER_CLIENT_SECRET
"""
import requests
from datetime import datetime, timedelta


class NaverClient:
    SEARCH_BASE = "https://openapi.naver.com/v1/search"
    DATALAB_BASE = "https://openapi.naver.com/v1/datalab"

    def __init__(self, client_id: str, client_secret: str):
        self.headers = {
            "X-Naver-Client-Id": client_id,
            "X-Naver-Client-Secret": client_secret,
            "Content-Type": "application/json",
        }
        self.client_id = client_id

    def _get(self, url, params):
        try:
            r = requests.get(url, headers=self.headers, params=params, timeout=10)
            if r.status_code == 200:
                return r.json()
            print(f"[네이버] {r.status_code}: {r.text[:200]}")
        except Exception as e:
            print(f"[네이버] 오류: {e}")
        return {}

    def _post(self, url, body):
        try:
            r = requests.post(url, headers=self.headers, json=body, timeout=10)
            if r.status_code == 200:
                return r.json()
            print(f"[네이버] {r.status_code}: {r.text[:200]}")
        except Exception as e:
            print(f"[네이버] 오류: {e}")
        return {}

    # ── 쇼핑 검색 ────────────────────────────────────────────
    def search_shopping(self, query: str, display: int = 20, sort: str = "sim") -> list[dict]:
        """
        네이버 쇼핑 검색
        sort: sim(정확도) | date(날짜) | asc(가격낮은순) | dsc(가격높은순)
        """
        data = self._get(f"{self.SEARCH_BASE}/shop.json",
                         {"query": query, "display": display, "sort": sort})
        items = data.get("items", [])
        results = []
        for item in items:
            results.append({
                "title":      item.get("title","").replace("<b>","").replace("</b>",""),
                "link":       item.get("link",""),
                "image":      item.get("image",""),
                "lprice":     int(item.get("lprice", 0)),
                "hprice":     int(item.get("hprice", 0)) if item.get("hprice") else 0,
                "mall_name":  item.get("mallName",""),
                "product_id": item.get("productId",""),
                "category1":  item.get("category1",""),
                "category2":  item.get("category2",""),
            })
        return results

    # ── 블로그 검색 ──────────────────────────────────────────
    def search_blog(self, query: str, display: int = 10) -> list[dict]:
        data = self._get(f"{self.SEARCH_BASE}/blog.json",
                         {"query": query, "display": display, "sort": "sim"})
        return [{"title": i.get("title","").replace("<b>","").replace("</b>",""),
                 "link": i.get("link",""),
                 "description": i.get("description","").replace("<b>","").replace("</b>",""),
                 "postdate": i.get("postdate","")}
                for i in data.get("items", [])]

    # ── 뉴스 검색 ────────────────────────────────────────────
    def search_news(self, query: str, display: int = 10) -> list[dict]:
        data = self._get(f"{self.SEARCH_BASE}/news.json",
                         {"query": query, "display": display, "sort": "date"})
        return [{"title": i.get("title","").replace("<b>","").replace("</b>",""),
                 "link": i.get("originallink", i.get("link","")),
                 "description": i.get("description","").replace("<b>","").replace("</b>",""),
                 "pubDate": i.get("pubDate","")}
                for i in data.get("items", [])]

    # ── 데이터랩: 검색어 트렌드 ─────────────────────────────
    def datalab_trend(self, keywords: list[str], period_months: int = 3) -> dict:
        """
        네이버 데이터랩 검색어 트렌드
        keywords: 비교할 키워드 리스트 (최대 5개 그룹, 각 그룹 최대 5개 키워드)
        """
        end   = datetime.now()
        start = end - timedelta(days=period_months * 30)

        keyword_groups = []
        for kw in keywords[:5]:
            keyword_groups.append({"groupName": kw, "keywords": [kw]})

        body = {
            "startDate": start.strftime("%Y-%m-%d"),
            "endDate":   end.strftime("%Y-%m-%d"),
            "timeUnit":  "week",
            "keywordGroups": keyword_groups,
        }
        return self._post(f"{self.DATALAB_BASE}/search", body)

    # ── 데이터랩: 쇼핑인사이트 카테고리 트렌드 ─────────────
    def datalab_shopping_category(self, category_name: str, category_param: str,
                                   period_months: int = 3) -> dict:
        """
        네이버 쇼핑인사이트 — 카테고리 트렌드
        category_param: 네이버 쇼핑 카테고리 코드 (예: "50000000" 패션의류)
        """
        end   = datetime.now()
        start = end - timedelta(days=period_months * 30)
        body = {
            "startDate": start.strftime("%Y-%m-%d"),
            "endDate":   end.strftime("%Y-%m-%d"),
            "timeUnit":  "week",
            "category":  [{"name": category_name, "param": [category_param]}],
            "device":    "mo",
            "gender":    "",
            "ages":      [],
        }
        return self._post(f"{self.DATALAB_BASE}/shopping/categories", body)

    # ── 데이터랩: 쇼핑인사이트 키워드 트렌드 ───────────────
    def datalab_shopping_keyword(self, category_param: str,
                                  keywords: list[str], period_months: int = 3) -> dict:
        """쇼핑인사이트 — 특정 카테고리 내 키워드 클릭 트렌드"""
        end   = datetime.now()
        start = end - timedelta(days=period_months * 30)
        kw_list = [{"name": kw, "param": [kw]} for kw in keywords[:5]]
        body = {
            "startDate": start.strftime("%Y-%m-%d"),
            "endDate":   end.strftime("%Y-%m-%d"),
            "timeUnit":  "week",
            "category":  category_param,
            "keyword":   kw_list,
            "device":    "",
            "gender":    "",
            "ages":      [],
        }
        return self._post(f"{self.DATALAB_BASE}/shopping/keywords", body)
