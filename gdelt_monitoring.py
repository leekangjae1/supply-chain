import requests
import pandas as pd
import json
import time
import os
from datetime import datetime, timezone
from urllib.parse import quote

# ============================================================
# GDELT Supply Chain Risk News Monitoring
# - 매 실행마다 모든 위험 유형(disaster / operation / policy_regulation) 검색
# - 8개 국가 × 모든 위험 키워드 검색
# - URL 기준 중복 제거
# - 429 / Timeout 재시도
# ============================================================

countries = [
    "Japan",
    "China",
    "South Korea",
    "Germany",
    "United States",
    "Mexico",
    "Vietnam",
    "India",
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

OUTPUT_JSON = "gdelt_results.json"
OUTPUT_CSV = "gdelt_monitoring.csv"
MAX_RECORDS = 50
TIMESPAN = "3d"
REQUEST_DELAY_SECONDS = 3
MAX_RETRIES = 3


def build_query(country: str, keyword: str) -> str:
    """국가명과 위험 키워드로 GDELT 검색 쿼리 생성."""
    words = keyword.split()
    if len(words) == 1:
        keyword_expr = keyword
    else:
        keyword_expr = f"{words[0]} near1 {' '.join(words[1:])}"
    return f'"{country}" {keyword_expr}'


def fetch_with_retry(url: str, query: str, max_retries: int = MAX_RETRIES):
    """GDELT 요청. 429 및 타임아웃 발생 시 제한적으로 재시도."""
    for attempt in range(max_retries):
        try:
            response = requests.get(url, timeout=40)

            if response.status_code == 200:
                try:
                    return response.json()
                except ValueError:
                    print(f"[ERROR] JSON 파싱 실패 | {query}")
                    return None

            if response.status_code == 429:
                wait_time = 30 * (attempt + 1)
                print(f"[429] 요청 제한: {query} → {wait_time}초 대기 후 재시도")
                time.sleep(wait_time)
                continue

            print(f"[ERROR] HTTP {response.status_code} | {query}")
            return None

        except requests.exceptions.Timeout:
            wait_time = 20 * (attempt + 1)
            print(f"[TIMEOUT] {query} → {wait_time}초 대기 후 재시도")
            time.sleep(wait_time)

        except requests.exceptions.RequestException as e:
            print(f"[ERROR] 요청 실패 | {query} | {e}")
            return None

    print(f"[ERROR] 최대 재시도 횟수 초과 | {query}")
    return None


def search_gdelt(query: str, risk_type: str, country: str, keyword: str) -> list:
    """GDELT에서 검색하고 필요한 기사 필드만 추출."""
    url = (
        "https://api.gdeltproject.org/api/v2/doc/doc?"
        f"query={quote(query)}"
        "&mode=artlist"
        "&format=json"
        f"&maxrecords={MAX_RECORDS}"
        "&sort=hybridrel"
        f"&timespan={TIMESPAN}"
    )

    data = fetch_with_retry(url, query)
    if data is None:
        return []

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
            "collected_at": datetime.now(timezone.utc).isoformat(),
        })

    return results


def load_existing(filepath: str) -> tuple[list, set]:
    """기존 JSON 결과를 읽고 URL 기준 중복 방지 집합 생성."""
    if not os.path.exists(filepath):
        return [], set()

    try:
        with open(filepath, "r", encoding="utf-8") as f:
            old_data = json.load(f)

        # 이전 파일이 {"results": [...]} 형식인 경우와 리스트 형식을 모두 처리
        if isinstance(old_data, dict):
            existing = old_data.get("results", [])
        elif isinstance(old_data, list):
            existing = old_data
        else:
            existing = []

        existing_urls = {
            item.get("url")
            for item in existing
            if isinstance(item, dict) and item.get("url")
        }
        return existing, existing_urls

    except (OSError, json.JSONDecodeError) as e:
        print(f"[WARN] 기존 결과 파일을 읽지 못했습니다: {e}")
        return [], set()


def main():
    existing_results, existing_urls = load_existing(OUTPUT_JSON)
    new_results = []

    # 모든 위험 유형을 매 실행마다 검색
    total_queries = len(countries) * sum(len(words) for words in risk_groups.values())
    query_number = 0

    print("=" * 65)
    print("GDELT 공급망 위험 뉴스 모니터링 시작")
    print(f"국가 수: {len(countries)}")
    print(f"위험 유형: {', '.join(risk_groups.keys())}")
    print(f"예상 검색 요청 수: {total_queries}")
    print(f"검색 기간: 최근 {TIMESPAN}")
    print("=" * 65)

    for country in countries:
        for risk_type, keywords in risk_groups.items():
            for keyword in keywords:
                query_number += 1
                query = build_query(country, keyword)
                print(f"[{query_number}/{total_queries}] [{risk_type}] Searching: {query}")

                results = search_gdelt(
                    query=query,
                    risk_type=risk_type,
                    country=country,
                    keyword=keyword,
                )

                added = 0
                for item in results:
                    article_url = item.get("url")
                    if article_url and article_url not in existing_urls:
                        new_results.append(item)
                        existing_urls.add(article_url)
                        added += 1

                print(f"  → {len(results)}건 수신 / {added}건 신규")
                time.sleep(REQUEST_DELAY_SECONDS)

    all_results = existing_results + new_results

    json_output = {
        "updated_at": datetime.now(timezone.utc).isoformat(),
        "selected_group": "all",
        "risk_groups_searched": list(risk_groups.keys()),
        "timespan": TIMESPAN,
        "new_count": len(new_results),
        "total_count": len(all_results),
        "results": all_results,
    }

    with open(OUTPUT_JSON, "w", encoding="utf-8") as f:
        json.dump(json_output, f, ensure_ascii=False, indent=2)

    if all_results:
        pd.DataFrame(all_results).to_csv(
            OUTPUT_CSV,
            index=False,
            encoding="utf-8-sig",
        )
        print(f"CSV 저장 완료: {OUTPUT_CSV}")
    else:
        print("[WARN] 저장할 기사가 없습니다.")

    print("\n모니터링 완료")
    print(f"검색 요청 수: {total_queries}")
    print(f"신규 기사 수: {len(new_results)}")
    print(f"누적 기사 수: {len(all_results)}")
    print(f"JSON 저장: {OUTPUT_JSON}")


if __name__ == "__main__":
    main()
