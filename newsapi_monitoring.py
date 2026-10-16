import json
import os
import time
from datetime import datetime, timedelta, timezone
from urllib.parse import urlparse

import pandas as pd
import requests

# ============================================================
# NewsAPI.ai (Event Registry) Supply Chain Risk News Monitoring
# Based on "현대차 공급망 뉴스 수집 쿼리 설계 보고서"
# - 11개국 x 6개 국가별 리스크 그룹 = 66개 쿼리
# - 전역 에너지/원자재 = 2개 쿼리
# - 해상 초크포인트 위험 = 3개 쿼리
# - 총 71개 쿼리
# - GDELT와 호환되는 results JSON 필드
# - URL 기준 중복 제거, 429/5xx/timeout 재시도
# ============================================================

API_URL = "https://eventregistry.org/api/v1/article/getArticles"
API_KEY = os.getenv("NEWSAPI_AI_API_KEY", "").strip()

OUTPUT_JSON = "newsapi_results.json"
OUTPUT_CSV = "newsapi_monitoring.csv"
MAX_RECORDS_PER_QUERY = int(os.getenv("NEWSAPI_MAX_RECORDS_PER_QUERY", "50"))
REQUEST_DELAY_SECONDS = float(os.getenv("NEWSAPI_REQUEST_DELAY_SECONDS", "1.5"))
MAX_RETRIES = int(os.getenv("NEWSAPI_MAX_RETRIES", "3"))
TIMEOUT_SECONDS = int(os.getenv("NEWSAPI_TIMEOUT_SECONDS", "45"))

# 기본은 GDELT 수집기와 비슷하게 최근 3일.
# 보고서 사례 기간으로 바꾸려면 GitHub Actions 환경변수에 다음을 설정:
# NEWSAPI_DATE_START=2026-02-01 / NEWSAPI_DATE_END=2026-03-31
_today = datetime.now(timezone.utc).date()
DEFAULT_DATE_START = (_today - timedelta(days=3)).isoformat()
DEFAULT_DATE_END = _today.isoformat()
DATE_START = os.getenv("NEWSAPI_DATE_START", DEFAULT_DATE_START)
DATE_END = os.getenv("NEWSAPI_DATE_END", DEFAULT_DATE_END)

COUNTRIES = [
    "South Korea", "China", "Japan", "Germany", "United States",
    "India", "Spain", "Romania", "Thailand", "Portugal", "Vietnam",
]

COUNTRY_RISK_GROUPS = {
    "disaster": [
        "earthquake", "flood", "typhoon", "tsunami", "wildfire",
        "hurricane", "drought", "heatwave", "cyclone",
    ],
    "operation": [
        "factory fire", "industrial accident", "plant shutdown",
        "production halt", "power outage", "utility failure",
    ],
    "labor": [
        "strike", "labor dispute", "walkout", "lockout",
        "worker shortage", "labor shortage",
    ],
    "policy_regulation": [
        "tariff", "sanctions", "import ban", "export ban",
        "trade restriction", "customs regulation",
    ],
    "logistics": [
        "port closure", "port congestion", "shipping disruption",
        "container shortage", "freight delay", "vessel rerouting",
    ],
    "geopolitical_conflict": [
        "war", "armed conflict", "military attack", "invasion", "blockade",
    ],
}

GLOBAL_GROUPS = {
    "energy": {
        "assets": [
            "LNG", "liquefied natural gas", "natural gas", "crude oil",
            "diesel", "coal", "electricity",
        ],
        "events": [
            "supply disruption", "shortage", "export reduction",
            "terminal outage", "production shutdown", "price spike",
        ],
    },
    "raw_materials": {
        "assets": [
            "copper", "gold", "manganese", "tin", "cobalt",
            "tantalum", "tungsten",
        ],
        "events": [
            "shortage", "mine disruption", "smelter outage",
            "export restriction", "supply disruption", "price spike",
        ],
    },
}

CHOKEPOINTS = [
    "Strait of Malacca", "North Sea", "Suez Canal", "China coast",
    "Mediterranean", "Gulf of Thailand", "Gulf of Tonkin", "Red Sea",
    "Strait of Hormuz",
]

CHOKEPOINT_RISK_GROUPS = {
    "chokepoint_disruption": [
        "blockade", "closure", "vessel attack", "maritime accident",
        "collision", "grounding", "piracy", "shipping disruption",
        "rerouting", "congestion",
    ],
    "chokepoint_disaster": [
        "earthquake", "flood", "typhoon", "tsunami", "hurricane",
    ],
    "chokepoint_conflict": [
        "war", "armed conflict", "military attack",
    ],
}


def keyword_condition(term: str) -> dict:
    """Event Registry AQL keyword condition. Phrases are passed as phrases."""
    return {"keyword": term}


def or_conditions(terms: list[str]) -> dict:
    return {"$or": [keyword_condition(term) for term in terms]}


def and_conditions(*conditions: dict) -> dict:
    return {"$and": list(conditions)}


def readable_or(terms: list[str]) -> str:
    return " OR ".join(f'"{term}"' if " " in term else term for term in terms)


def build_query_records() -> list[dict]:
    records = []

    # 1) 국가별: 국가명 AND (같은 리스크 그룹 안의 키워드 OR)
    for country in COUNTRIES:
        for risk_type, terms in COUNTRY_RISK_GROUPS.items():
            query_text = f'"{country}" ({readable_or(terms)})'
            records.append({
                "risk_type": risk_type,
                "anchor": country,
                "country": country,
                "keyword": readable_or(terms),
                "query": query_text,
                "aql": and_conditions(keyword_condition(country), or_conditions(terms)),
            })

    # 2) 전역 에너지/원자재: (품목 OR) AND (사건 표현 OR)
    for risk_type, group in GLOBAL_GROUPS.items():
        query_text = f'({readable_or(group["assets"])}) ({readable_or(group["events"])})'
        records.append({
            "risk_type": risk_type,
            "anchor": "global",
            "country": "global",
            "keyword": f'{readable_or(group["assets"])} AND ({readable_or(group["events"])})',
            "query": query_text,
            "aql": and_conditions(or_conditions(group["assets"]), or_conditions(group["events"])),
        })

    # 3) 초크포인트: (해역 OR) AND (해당 위험 표현 OR)
    for risk_type, terms in CHOKEPOINT_RISK_GROUPS.items():
        query_text = f'({readable_or(CHOKEPOINTS)}) ({readable_or(terms)})'
        records.append({
            "risk_type": risk_type,
            "anchor": "chokepoints",
            "country": "chokepoints",
            "keyword": f'{readable_or(CHOKEPOINTS)} AND ({readable_or(terms)})',
            "query": query_text,
            "aql": and_conditions(or_conditions(CHOKEPOINTS), or_conditions(terms)),
        })

    return records


def fetch_with_retry(payload: dict, query_text: str) -> dict | None:
    """POST API call with bounded retries for throttling, server errors and timeouts."""
    if not API_KEY:
        raise RuntimeError(
            "NEWSAPI_AI_API_KEY 환경변수가 없습니다. NewsAPI.ai API 키를 환경변수로 설정하세요."
        )

    for attempt in range(MAX_RETRIES):
        try:
            response = requests.post(
                API_URL,
                json=payload,
                headers={"Content-Type": "application/json"},
                timeout=TIMEOUT_SECONDS,
            )

            if response.status_code == 200:
                try:
                    data = response.json()
                except ValueError:
                    print(f"[ERROR] JSON 파싱 실패 | {query_text}")
                    return None

                # API는 HTTP 200이어도 응답 본문에 오류를 반환할 수 있음
                if isinstance(data, dict) and data.get("error"):
                    print(f"[API ERROR] {data.get('error')} | {query_text}")
                    return None
                return data

            if response.status_code == 429 or response.status_code >= 500:
                wait_time = min(60, 5 * (attempt + 1) ** 2)
                print(f"[HTTP {response.status_code}] 재시도 대기 {wait_time}초 | {query_text}")
                time.sleep(wait_time)
                continue

            print(f"[ERROR] HTTP {response.status_code} | {query_text} | {response.text[:500]}")
            return None

        except (requests.exceptions.Timeout, requests.exceptions.ConnectionError) as exc:
            wait_time = min(60, 5 * (attempt + 1) ** 2)
            print(f"[TIMEOUT/CONNECTION] {exc} | {wait_time}초 후 재시도 | {query_text}")
            time.sleep(wait_time)
        except requests.exceptions.RequestException as exc:
            print(f"[ERROR] 요청 실패 | {query_text} | {exc}")
            return None

    print(f"[ERROR] 최대 재시도 횟수 초과 | {query_text}")
    return None


def extract_articles(data: dict | None) -> list[dict]:
    """Handle Event Registry's usual articles.results response shape."""
    if not isinstance(data, dict):
        return []
    articles = data.get("articles", {})
    if isinstance(articles, dict):
        rows = articles.get("results", [])
        return rows if isinstance(rows, list) else []
    if isinstance(articles, list):
        return articles
    return []


def domain_from_url(url: str) -> str:
    try:
        return urlparse(url).netloc.lower().removeprefix("www.")
    except Exception:
        return ""


def source_country_from_article(article: dict) -> str:
    """Best-effort source country extraction; empty string when not supplied."""
    source = article.get("source") or {}
    if not isinstance(source, dict):
        return ""
    location = source.get("location") or {}
    if isinstance(location, dict):
        label = location.get("label") or {}
        if isinstance(label, dict):
            # Prefer English label, otherwise first available label.
            if label.get("eng"):
                return str(label["eng"])
            for value in label.values():
                if value:
                    return str(value)
        if isinstance(location.get("country"), str):
            return location["country"]
    return str(source.get("country", "") or "")


def normalize_article(article: dict, record: dict) -> dict | None:
    article_url = article.get("url") or article.get("uri") or ""
    if not isinstance(article_url, str) or not article_url.strip():
        return None

    title = article.get("title", "")
    if isinstance(title, dict):
        title = title.get("eng") or next(iter(title.values()), "")

    published_at = (
        article.get("dateTimePub")
        or article.get("dateTime")
        or article.get("date")
        or ""
    )
    language = article.get("lang", "") or ""
    source = article.get("source") or {}
    if isinstance(source, dict):
        source_domain = source.get("uri", "") or ""
    else:
        source_domain = ""

    # GDELT 호환 필드명을 유지. global/chokepoints 검색은 country에 앵커를 기록.
    return {
        "risk_type": record["risk_type"],
        "country": record["country"],
        "keyword": record["keyword"],
        "query": record["query"],
        "title": str(title or ""),
        "url": article_url.strip(),
        "domain": domain_from_url(article_url) or source_domain,
        "language": language,
        "source_country": source_country_from_article(article),
        "published_at": published_at,
        "collected_at": datetime.now(timezone.utc).isoformat(),
    }


def load_existing(filepath: str) -> tuple[list[dict], set[str]]:
    if not os.path.exists(filepath):
        return [], set()
    try:
        with open(filepath, "r", encoding="utf-8") as f:
            old_data = json.load(f)
        if isinstance(old_data, dict):
            existing = old_data.get("results", [])
        elif isinstance(old_data, list):
            existing = old_data
        else:
            existing = []
        if not isinstance(existing, list):
            existing = []
        urls = {
            item.get("url") for item in existing
            if isinstance(item, dict) and item.get("url")
        }
        return existing, urls
    except (OSError, json.JSONDecodeError) as exc:
        print(f"[WARN] 기존 결과 파일을 읽지 못했습니다: {exc}")
        return [], set()


def build_payload(record: dict) -> dict:
    # API의 Advanced Query Language(AQL)를 사용해 AND/OR 그룹을 구조적으로 전달.
    # 검색 기간은 기사 발행일 기준으로 제한한다.
    return {
        "query": {
            "$query": {
                "$and": [
                    record["aql"],
                    {"dateStart": DATE_START, "dateEnd": DATE_END},
                ]
            }
        },
        "resultType": "articles",
        "articlesPage": 1,
        "articlesCount": min(max(MAX_RECORDS_PER_QUERY, 1), 100),
        "articlesSortBy": "date",
        "articlesSortByAsc": False,
        "articlesArticleBodyLen": 0,
        "dataType": ["news"],
        "apiKey": API_KEY,
    }


def main() -> None:
    if not API_KEY:
        raise SystemExit(
            "오류: NEWSAPI_AI_API_KEY 환경변수를 설정해야 합니다.\n"
            "GitHub Actions에서는 Settings > Secrets and variables > Actions에 등록하고,\n"
            "workflow의 env에서 NEWSAPI_AI_API_KEY: ${{ secrets.NEWSAPI_AI_API_KEY }} 로 전달하세요."
        )

    query_records = build_query_records()
    expected = len(COUNTRIES) * len(COUNTRY_RISK_GROUPS) + len(GLOBAL_GROUPS) + len(CHOKEPOINT_RISK_GROUPS)
    if len(query_records) != 71:
        raise RuntimeError(f"쿼리 개수 검증 실패: expected 71, got {len(query_records)}")

    existing_results, existing_urls = load_existing(OUTPUT_JSON)
    new_results = []
    failed_queries = []

    print("=" * 72)
    print("NewsAPI.ai 현대차 공급망 위험 뉴스 모니터링 시작")
    print(f"국가 수: {len(COUNTRIES)} | 국가별 위험 유형: {len(COUNTRY_RISK_GROUPS)}")
    print("쿼리 구성: 국가별 66 + 에너지/원자재 2 + 초크포인트 3 = 71")
    print(f"검색 기간: {DATE_START} ~ {DATE_END}")
    print(f"쿼리당 최대 기사: {MAX_RECORDS_PER_QUERY}")
    print("=" * 72)

    for index, record in enumerate(query_records, start=1):
        print(f"[{index}/{len(query_records)}] [{record['risk_type']}] {record['query']}")
        payload = build_payload(record)
        data = fetch_with_retry(payload, record["query"])
        if data is None:
            failed_queries.append({"risk_type": record["risk_type"], "query": record["query"]})
            time.sleep(REQUEST_DELAY_SECONDS)
            continue

        articles = extract_articles(data)
        added = 0
        for article in articles:
            normalized = normalize_article(article, record)
            if not normalized:
                continue
            url = normalized["url"]
            if url not in existing_urls:
                new_results.append(normalized)
                existing_urls.add(url)
                added += 1
        print(f"  -> {len(articles)}건 수신 / {added}건 신규")
        time.sleep(REQUEST_DELAY_SECONDS)

    all_results = existing_results + new_results
    output = {
        "updated_at": datetime.now(timezone.utc).isoformat(),
        "selected_group": "all",
        "source": "newsapi.ai",
        "risk_groups_searched": list(COUNTRY_RISK_GROUPS.keys()) + list(GLOBAL_GROUPS.keys()) + list(CHOKEPOINT_RISK_GROUPS.keys()),
        "query_count": len(query_records),
        "date_start": DATE_START,
        "date_end": DATE_END,
        "new_count": len(new_results),
        "total_count": len(all_results),
        "failed_query_count": len(failed_queries),
        "failed_queries": failed_queries,
        "results": all_results,
    }

    with open(OUTPUT_JSON, "w", encoding="utf-8") as f:
        json.dump(output, f, ensure_ascii=False, indent=2)

    if all_results:
        pd.DataFrame(all_results).to_csv(OUTPUT_CSV, index=False, encoding="utf-8-sig")
        print(f"CSV 저장 완료: {OUTPUT_CSV}")
    else:
        print("[WARN] 저장된 기사가 없습니다. API 키, 검색 기간, 요금제/토큰 사용량을 확인하세요.")

    print("\n모니터링 완료")
    print(f"검색 쿼리 수: {len(query_records)}")
    print(f"실패 쿼리 수: {len(failed_queries)}")
    print(f"신규 기사 수: {len(new_results)}")
    print(f"누적 기사 수: {len(all_results)}")
    print(f"JSON 저장: {OUTPUT_JSON}")


if __name__ == "__main__":
    main()
