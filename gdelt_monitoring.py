import requests
import pandas as pd
import json
import time
import os
from datetime import datetime
from urllib.parse import quote


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

risk_groups = {
    "disaster": [
        "earthquake",
        "flood",
        "typhoon",
        "tsunami",
        "wildfire",
        "hurricane",
    ],
    "operation": [
        "factory fire",
        "strike",
        "port strike",
        "port closure",
        "power outage",
        "plant shutdown",
    ],
    "policy_regulation": [
        "tariff",
        "sanctions",
        "import ban",
        "export ban",
        "trade restriction",
        "labor law",
        "customs regulation",
    ],
}

group_names = list(risk_groups.keys())
selected_group = group_names[datetime.utcnow().hour % len(group_names)]

print(f"Selected group: {selected_group}")

existing_results = []
existing_urls = set()

if os.path.exists("gdelt_results.json"):
    try:
        with open("gdelt_results.json", "r", encoding="utf-8") as f:
            old_data = json.load(f)
            existing_results = old_data.get("results", [])

        for item in existing_results:
            url = item.get("url")
            if url:
                existing_urls.add(url)

    except Exception:
        existing_results = []
        existing_urls = set()


def build_query(country: str, keyword: str) -> str:
    """
    쿼리 완화 전략:
    - 국가명: 따옴표 유지 (exact match) → 국가 특정성 보장
    - 키워드: 따옴표 제거 (soft match)
        - 단일 단어: 그대로 사용         예) earthquake
        - 복합 단어: near1 연산자 적용   예) factory near1 fire
          → 두 단어가 인접해있으면 매칭, 어순 무관
          → "factory fire" exact보다 훨씬 많은 기사 포착
    """
    words = keyword.split()

    if len(words) == 1:
        # 단일 단어: soft match
        keyword_expr = keyword
    else:
        # 복합 단어: near1 연산자로 인접 매칭
        keyword_expr = f"{words[0]} near1 {' '.join(words[1:])}"

    return f'"{country}" {keyword_expr}'


def search_gdelt(query, risk_type, country, keyword):
    url = (
        "https://api.gdeltproject.org/api/v2/doc/doc?"
        f"query={quote(query)}"
        "&mode=artlist"
        "&format=json"
        "&maxrecords=50"
        "&sort=hybridrel"
        "&timespan=3d"
    )

    try:
        response = requests.get(url, timeout=30)

        if response.status_code != 200:
            print(f"  [ERROR] status {response.status_code} | {query}")
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
        print(f"  [ERROR] {query} | {e}")
        return []


new_results = []

for country in countries:
    for keyword in risk_groups[selected_group]:
        query = build_query(country, keyword)
        print(f"Searching: {query}")

        results = search_gdelt(
            query=query,
            risk_type=selected_group,
            country=country,
            keyword=keyword
        )

        added = 0
        for item in results:
            url = item.get("url")
            if url and url not in existing_urls:
                new_results.append(item)
                existing_urls.add(url)
                added += 1

        print(f"  → {len(results)}건 수신 / {added}건 신규")
        time.sleep(3)


all_results = existing_results + new_results

json_output = {
    "updated_at": datetime.utcnow().isoformat(),
    "selected_group": selected_group,
    "timespan": "3d",
    "new_count": len(new_results),
    "total_count": len(all_results),
    "results": all_results
}

with open("gdelt_results.json", "w", encoding="utf-8") as f:
    json.dump(json_output, f, ensure_ascii=False, indent=2)

df = pd.DataFrame(all_results)
df.to_csv("gdelt_monitoring.csv", index=False, encoding="utf-8-sig")

print("\nDone.")
print(f"Selected group : {selected_group}")
print(f"New articles   : {len(new_results)}")
print(f"Total articles : {len(all_results)}")
