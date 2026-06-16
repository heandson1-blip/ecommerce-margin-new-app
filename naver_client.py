"""
naver_client.py v3 — 네이버 API 클라이언트
- 블로그: bloggername, bloggerlink 필드 포함
- 쇼핑인사이트: 다중 키워드 지원 확인
- display=100 (최대), 페이징 지원
"""
import requests, json
import pandas as pd


class NaverClient:
    SEARCH_BASE  = "https://openapi.naver.com/v1/search"
    DATALAB_BASE = "https://openapi.naver.com/v1/datalab"

    def __init__(self, client_id: str, client_secret: str):
        self.headers = {
            "X-Naver-Client-Id":     client_id,
            "X-Naver-Client-Secret": client_secret,
            "Content-Type":          "application/json",
        }

    def _get(self, path, params):
        try:
            r = requests.get(f"{self.SEARCH_BASE}/{path}",
                             headers=self.headers, params=params, timeout=12)
            if r.status_code == 200: return r.json()
            print(f"[네이버] {r.status_code}: {r.text[:200]}")
        except Exception as e: print(f"[네이버 오류] {e}")
        return {}

    def _post(self, url, body):
        try:
            r = requests.post(url, headers=self.headers,
                              data=json.dumps(body), timeout=12)
            if r.status_code == 200: return r.json()
            print(f"[네이버] {r.status_code}: {r.text[:200]}")
        except Exception as e: print(f"[네이버 오류] {e}")
        return {}

    @staticmethod
    def _clean(text):
        if not text: return ""
        return (text.replace("<b>","").replace("</b>","")
                    .replace("&quot;",'"').replace("&lt;","<")
                    .replace("&gt;",">").replace("&amp;","&"))

    def search_shopping(self, keywords, display=100, page=1, sort="sim"):
        display = min(display, 100)
        start   = (page - 1) * display + 1
        rows = []
        for kw in keywords:
            data = self._get("shop.json", {"query":kw,"display":display,"start":start,"sort":sort})
            for item in data.get("items",[]):
                rows.append({
                    "search_keyword": kw,
                    "title":    self._clean(item.get("title","")),
                    "link":     item.get("link",""),
                    "image":    item.get("image",""),
                    "lprice":   int(item.get("lprice",0)) if item.get("lprice") else 0,
                    "mall_name": item.get("mallName",""),
                    "product_id": item.get("productId",""),
                    "category1": item.get("category1",""),
                    "category2": item.get("category2",""),
                })
        return pd.DataFrame(rows) if rows else pd.DataFrame()

    def search_blog(self, keywords, display=100, page=1):
        """블로그 검색 — bloggername, bloggerlink 포함"""
        start = (page-1)*min(display,100)+1
        rows=[]
        for kw in keywords:
            data=self._get("blog.json",{"query":kw,"display":min(display,100),"start":start,"sort":"date"})
            for item in data.get("items",[]):
                rows.append({
                    "search_keyword": kw,
                    "title":       self._clean(item.get("title","")),
                    "link":        item.get("link",""),
                    "description": self._clean(item.get("description","")),
                    "bloggername": item.get("bloggername",""),
                    "bloggerlink": item.get("bloggerlink",""),
                    "postdate":    item.get("postdate",""),
                })
        return pd.DataFrame(rows) if rows else pd.DataFrame()

    def search_news(self, keywords, display=100, page=1):
        start=(page-1)*min(display,100)+1
        rows=[]
        for kw in keywords:
            data=self._get("news.json",{"query":kw,"display":min(display,100),"start":start,"sort":"date"})
            for item in data.get("items",[]):
                rows.append({
                    "search_keyword": kw,
                    "title":       self._clean(item.get("title","")),
                    "link":        item.get("originallink",item.get("link","")),
                    "description": self._clean(item.get("description","")),
                    "pubDate":     item.get("pubDate",""),
                })
        return pd.DataFrame(rows) if rows else pd.DataFrame()

    def search_cafe(self, keywords, display=100, page=1):
        start=(page-1)*min(display,100)+1
        rows=[]
        for kw in keywords:
            data=self._get("cafearticle.json",{"query":kw,"display":min(display,100),"start":start,"sort":"date"})
            for item in data.get("items",[]):
                rows.append({
                    "search_keyword": kw,
                    "title":       self._clean(item.get("title","")),
                    "link":        item.get("link",""),
                    "description": self._clean(item.get("description","")),
                    "cafename":    item.get("cafename",""),
                    "cafeurl":     item.get("cafeurl",""),
                })
        return pd.DataFrame(rows) if rows else pd.DataFrame()

    def datalab_trend(self, keywords, start_date, end_date, time_unit="date", gender="", ages=None):
        body={
            "startDate":start_date,"endDate":end_date,"timeUnit":time_unit,
            "keywordGroups":[{"groupName":k,"keywords":[k]} for k in keywords[:5]],
        }
        if gender: body["gender"]=gender
        if ages:   body["ages"]=ages
        data=self._post(f"{self.DATALAB_BASE}/search",body)
        results=data.get("results",[])
        if not results: return pd.DataFrame()
        dfs=[pd.DataFrame(r["data"]).assign(keyword=r["title"]) for r in results if r.get("data")]
        return pd.concat(dfs) if dfs else pd.DataFrame()

    def datalab_shopping_insight(self, category_id, keywords, start_date, end_date, time_unit="date"):
        """
        쇼핑인사이트 — 최대 5개 키워드 동시 조회
        API가 keyword 배열을 받아 results 배열로 반환
        """
        kw_list = [{"name": k, "param": [k]} for k in keywords[:5]]
        body={
            "startDate":start_date,"endDate":end_date,"timeUnit":time_unit,
            "category":category_id,
            "keyword": kw_list,
        }
        data=self._post(f"{self.DATALAB_BASE}/shopping/category/keywords",body)
        results=data.get("results",[])
        if not results:
            print(f"[쇼핑인사이트] 결과 없음. 응답: {data}")
            return pd.DataFrame()
        dfs=[]
        for r in results:
            kw_name = r.get("title","")
            if r.get("data"):
                df=pd.DataFrame(r["data"])
                df["keyword"]=kw_name
                dfs.append(df)
        result_df = pd.concat(dfs) if dfs else pd.DataFrame()
        if not result_df.empty:
            print(f"[쇼핑인사이트] 키워드 {result_df['keyword'].unique().tolist()} 수집 완료")
        return result_df

    INSIGHT_CATEGORIES = {
        "패션의류":"50000000","패션잡화":"50000001","화장품/미용":"50000002",
        "디지털/가전":"50000003","가구/인테리어":"50000004",
        "출산/육아":"50000005","식품":"50000006","스포츠/레저":"50000007",
        "생활/건강":"50000008","여가/생활편의":"50000009",
    }
