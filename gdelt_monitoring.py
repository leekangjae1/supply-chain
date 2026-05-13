import requests
import pandas as pd
import json
import time
from datetime import datetime
from urllib.parse import quote


# =========================
# 1. 국가 리스트
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
# 2. 리스크 키워드
# =========================

disaster_keywords = [
    "earthquake",
    "flood",
    "typhoon",
    "wildfire",
    "landslide"
]

operation_keywords = [
    "factory fire",
    "strike",
    "power outage",
    "production halt",
    "port disruption",
    "customs delay",
    "logistics disruption"
]

policy_keywords = [
    "export control",
    "import restriction",
    "trade restriction",
    "tariff",
    "trade sanction",
    "industrial policy",
    "manufacturing policy",
    "energy policy",
    "electricity regulation",
    "carbon regulation",
    "emission regulation",
    "labor law",
    "minimum wage",
    "port regulation",
    "shipping regulation",
    "customs regulation",
    "transport restriction"
]


# =========================
# 3. 키워드 묶기
# =========================
risk_groups = {
    "disaster": disaster_keywords,
    "operation": operation_keywords,
    "policy_regulation": policy_keywords
}


# =========================
# 4. GDELT 검색 함수
# =========================
def search_gdelt(query, risk_type, country, keyword, max_records=10):
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
                "risk_type": risk_type,
                "country": country,
                "keyword": keyword,
                "query": query,
                "title": article.get("title", ""),
                "url": article.get("url", ""),
                "domain": article.get("domain", ""),
                "language": article.get("language", ""),
                "source_country": article.get("sourceCountry", ""),
                "published_at": article.get("seendate", "")
            })

        return results

    except Exception as e:
        print(f"[ERROR] {query} | {e}")
        return []


# =========================
# 5. 전체 검색 실행
# =========================
all_results = []

for country in countries:
    for risk_type, keywords in risk_groups.items():
        for keyword in keywords:
            query = f'"{country}" "{keyword}"'

            print(f"Searching: {query}")

            results = search_gdelt(
                query=query,
                risk_type=risk_type,
                country=country,
                keyword=keyword,
                max_records=10
            )

            all_results.extend(results)

            time.sleep(1)


# =========================
# 6. URL 기준 중복 제거
# =========================
unique_results = []
seen_urls = set()

for item in all_results:
    url = item.get("url")

    if url and url not in seen_urls:
        unique_results.append(item)
        seen_urls.add(url)


# =========================
# 7. JSON 저장
# =========================
json_output = {
    "created_at": datetime.utcnow().isoformat(),
    "timespan": "30d",
    "total_count": len(unique_results),
    "results": unique_results
}

with open("gdelt_results.json", "w", encoding="utf-8") as f:
    json.dump(json_output, f, ensure_ascii=False, indent=2)


# =========================
# 8. CSV 저장
# =========================
df = pd.DataFrame(unique_results)
df.to_csv("gdelt_monitoring.csv", index=False, encoding="utf-8-sig")


print("Done.")
print(f"Total articles: {len(unique_results)}")
