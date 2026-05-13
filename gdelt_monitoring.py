import requests
import pandas as pd
import json
from datetime import datetime
from urllib.parse import quote
import time

# =========================
# 1. 검색할 국가
# =========================
countries = [
    "Japan",
    "China",
    "South Korea",
    "Germany",
    "United States",
    "Mexico",
    "Vietnam",
    "India"
]

# =========================
# 2. 공급망 리스크 키워드
# 처음에는 너무 복잡하게 하지 말고 2단어 조합 위주
# =========================
risk_keywords = [
    "earthquake",
    "flood",
    "factory fire",
    "strike",
    "power outage",
    "production halt",
    "port disruption"
]

# =========================
# 3. GDELT 검색 함수
# =========================
def search_gdelt(query, max_records=10):
    encoded_query = quote(query)

    url = (
        "https://api.gdeltproject.org/api/v2/doc/doc?"
        f"query={encoded_query}"
        "&mode=artlist"
        "&format=json"
        f"&maxrecords={max_records}"
        "&sort=hybridrel"
        "&timespan=30d"
    )

    try:
        response = requests.get(url, timeout=20)

        if response.status_code != 200:
            print(f"[ERROR] {query} | status code: {response.status_code}")
            return []

        data = response.json()
        articles = data.get("articles", [])

        results = []

        for article in articles:
            results.append({
                "query": query,
                "title": article.get("title", ""),
                "url": article.get("url", ""),
                "source": article.get("sourceCountry", ""),
                "language": article.get("language", ""),
                "published_at": article.get("seendate", ""),
                "domain": article.get("domain", "")
            })

        return results

    except Exception as e:
        print(f"[ERROR] {query} | {e}")
        return []


# =========================
# 4. 전체 쿼리 실행
# =========================
all_results = []

for country in countries:
    for risk in risk_keywords:
        query = f'"{country}" "{risk}"'
        print(f"Searching: {query}")

        results = search_gdelt(query)

        all_results.extend(results)

        time.sleep(1)  # GDELT 서버 부담 줄이기


# =========================
# 5. 중복 제거
# =========================
unique_results = []
seen_urls = set()

for item in all_results:
    url = item.get("url")

    if url and url not in seen_urls:
        unique_results.append(item)
        seen_urls.add(url)


# =========================
# 6. JSON 저장
# =========================
json_output = {
    "created_at": datetime.utcnow().isoformat(),
    "total_count": len(unique_results),
    "results": unique_results
}

with open("gdelt_results.json", "w", encoding="utf-8") as f:
    json.dump(json_output, f, ensure_ascii=False, indent=2)


# =========================
# 7. CSV 저장
# =========================
df = pd.DataFrame(unique_results)
df.to_csv("gdelt_monitoring.csv", index=False, encoding="utf-8-sig")


print("Done.")
print(f"Total articles: {len(unique_results)}")
