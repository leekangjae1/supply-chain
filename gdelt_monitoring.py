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


def build_query(country: str, keyword: str) -> str:
    words = keyword.split()
    if len(words) == 1:
        keyword_expr = keyword
    else:
        keyword_expr = f"{words[0]} near1 {' '.join(words[1:])}"
    return f'"{country}" {keyword_expr}'


def fetch_with_retry(url: str, query: str, max_retries: int = 3):
    """
    ✅ FIX: fetch_with_retry를 search_gdelt 바깥으로 분리 (독립 함수화)
    → 이전 코드는 내부 중첩 함수였는데, 반환값(data)을 쓰지 않고
      바깥 스코프의 response를 또 참조하는 NameError 버그가 있었음
    """
    for attempt in range(max_retries):
        try:
            response = requests.get(url, timeout=40)

            if response.status_code == 200:
                return response.json()

            if response.status_code == 429:
                wait_time = 30 * (attempt + 1)
                print(f"[429] Rate limit: {query} → {wait_time}초 대기 후 재시도")
                time.sleep(wait_time)
                continue

            print(f"[ERROR] status {response.status_code} | {query}")
            return None

        except requests.exceptions.Timeout:
            wait_time = 20 * (attempt + 1)
            print(f"[TIMEOUT] {query} → {wait_time}초 대기 후 재시도")
            time.sleep(wait_time)

        except Exception as e:
            print(f"[ERROR] {query} | {e}")
            return None

    return None


def search_gdelt(query: str, risk_type: str, country: str, keyword: str) -> list:
    url = (
        "https://api.gdeltproject.org/api/v2/doc/doc?"
        f"query={quote(query)}"
        "&mode=artlist"
        "&format=json"
        "&maxrecords=50"
        "&sort=hybridrel"
        "&timespan=3d"
    )

    # ✅ FIX: fetch_with_retry 반환값(data)만 사용, response 변수 참조 제거
    data = fetch_with_retry(url, query)

    if data is None:
        return []

    # ✅ FIX: 이전 코드는 data를 받아놓고 response.json()으로 덮어써버리는 버그가 있었음
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


def load_existing(filepath: str) -> tuple[list, set]:
    """기존 저장 결과와 URL 집합을 로드"""
    if not os.path.exists(filepath):
        return [], set()

    try:
        with open(filepath, "r", encoding="utf-8") as f:
            old_data = json.load(f)
        existing = old_data.get("results", [])
        existing_urls = {item["url"] for item in existing if item.get("url")}
        return existing, existing_urls
    except Exception as e:
        print(f"[WARN] 기존 파일 로드 실패: {e}")
        return [], set()


def main():
    group_names = list(risk_groups.keys())
    selected_group = group_names[datetime.utcnow().hour % len(group_names)]
    print(f"Selected group: {selected_group}")

    existing_results, existing_urls = load_existing("gdelt_results.json")

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

    # ✅ FIX: all_results가 비어있을 때 DataFrame 저장 시도해도 안전하게 처리
    if all_results:
        df = pd.DataFrame(all_results)
        df.to_csv("gdelt_monitoring.csv", index=False, encoding="utf-8-sig")
    else:
        print("[WARN] 저장할 기사가 없습니다.")

    print("\nDone.")
    print(f"Selected group : {selected_group}")
    print(f"New articles   : {len(new_results)}")
    print(f"Total articles : {len(all_results)}")


if __name__ == "__main__":
    main()
