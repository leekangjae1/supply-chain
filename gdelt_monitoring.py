import requests
import pandas as pd
import json
import time
import os
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
risk_groups = {
    "disaster": [
        "earthquake",
        "flood",
        "typhoon",
        "wildfire",
        "landslide"
    ],
    "operation": [
        "factory fire",
        "strike",
        "power outage",
        "production halt",
        "port disruption",
        "customs delay",
        "logistics disruption"
    ],
    "policy_regulation": [
        "export control",
        "import restriction",
        "trade restriction",
        "tariff",
        "trade sanction",
        "industrial policy",
        "energy policy",
        "electricity regulation",
        "carbon regulation",
        "emission regulation",
        "labor law",
        "minimum wage",
        "port regulation",
        "customs regulation",
        "transport restriction"
    ]
}


# =========================
# 3. 실행할 카테고리 선택
# GitHub Actions에서 RISK_GROUP 설정 가능
# 없으면 전체 실행
# 예: disaster / operation / policy_regulation / all
# =========================
selected_group = os.getenv("RISK_GROUP", "all")

if selected_group == "all":
    selected_risk_groups = risk_groups
else:
    selected_risk_groups = {
        selected_group: risk_groups[selected_group]
    }


# =========================
# 4. 기존 결과 불러오기
# =========================
existing_results = []
existing_urls = set()

if os.path.exists("gdelt_results.json"):
    try:
        with open("gdelt_results.json", "r", encoding="utf-8") as f:
            old_data = json.load(f)
            existing_results = old_data.get("results", [])

        for item in existing_results:
            if item.get("url"):
                existing_urls.add(item["url"])

    except Exception:
        existing_results = []
        existing_urls = set()


# =========================
# 5. GDELT 검색 함수
# =========================
def search_gdelt(query, risk_type, country, keyword, max_records=5):
    encoded_query = quote(query)

    url = (
        "https://api.gdeltproject.org/api/v2/doc/doc?"
        f"query={encoded_query}"
        "&mode=artlist"
        "&format=json"
        f"&maxrecords={max_records}"
        "&sort=hybridrel"
        "&timespan=7d"
    )

    for attempt in range(3):
        try:
            response = requests.get(url, timeout=20)

            if response.status_code == 429:
                print(f"[RATE LIMIT] {query} | retrying...")
                time.sleep(3)
                continue

            if response.status_code != 200:
                print(f"[ERROR] {query} | status code: {response.status_code}")
                return []

            data = response.json()
            articles = data.get("articles", [])

            results = []

            for article in articles:
                article_url = article.get("url", "")

                if not article_url:
                    continue

                results.append({
                    "risk_type": risk_type,
                    "country": country,
                    "keyword": keyword,
                    "query": query,
                    "title": article.get("title", ""),
                    "url": article_url,
                    "domain": article.get("domain", ""),
                    "language": article.get("language", ""),
                    "source_country": article.get("sourceCountry", ""),
                    "published_at": article.get("seendate", ""),
                    "collected_at": datetime.utcnow().isoformat()
                })

            return results

        except Exception as e:
            print(f"[ERROR] {query} | attempt {attempt + 1} | {e}")
            time.sleep(2)

    return []


# =========================
# 6. 전체 검색 실행
# =========================
new_results = []

for country in countries:
    for risk_type, keywords in selected_risk_groups.items():
        for keyword in keywords:
            query = f'"{country}" "{keyword}"'
            print(f"Searching: {query}")

            results = search_gdelt(
                query=query,
                risk_type=risk_type,
                country=country,
                keyword=keyword,
                max_records=5
            )

            for item in results:
                url = item.get("url")

                if url and url not in existing_urls:
                    new_results.append(item)
                    existing_urls.add(url)

            time.sleep(0.4)


# =========================
# 7. 기존 결과 + 신규 결과 합치기
# =========================
all_results = existing_results + new_results


# =========================
# 8. JSON 저장
# =========================
json_output = {
    "updated_at": datetime.utcnow().isoformat(),
    "timespan": "7d",
    "selected_group": selected_group,
    "new_count": len(new_results),
    "total_count": len(all_results),
    "results": all_results
}

with open("gdelt_results.json", "w", encoding="utf-8") as f:
    json.dump(json_output, f, ensure_ascii=False, indent=2)


# =========================
# 9. CSV 저장
# =========================
df = pd.DataFrame(all_results)
df.to_csv("gdelt_monitoring.csv", index=False, encoding="utf-8-sig")


print("Done.")
print(f"Selected group: {selected_group}")
print(f"New articles: {len(new_results)}")
print(f"Total articles: {len(all_results)}")
