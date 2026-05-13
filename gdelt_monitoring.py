import requests
import json
import time
from datetime import datetime

# =========================
# 국가 설정
# =========================

COUNTRIES = {
    "China": {"local": "中国", "lang": "chinese"},
    "Germany": {"local": "Deutschland", "lang": "german"},
    "Portugal": {"local": "Portugal", "lang": "portuguese"},
    "Japan": {"local": "日本", "lang": "japanese"},
    "Spain": {"local": "España", "lang": "spanish"},
    "Romania": {"local": "România", "lang": "romanian"},
    "Thailand": {"local": "ประเทศไทย", "lang": "thai"},
    "South Korea": {"local": "한국", "lang": "korean"}
}

# =========================
# 리스크 설정
# =========================

RISKS = {

    "earthquake": {
        "China": ["地震"],
        "Germany": ["Erdbeben"],
        "Portugal": ["terremoto"],
        "Japan": ["地震"],
        "Spain": ["terremoto"],
        "Romania": ["cutremur"],
        "Thailand": ["แผ่นดินไหว"],
        "South Korea": ["지진"]
    },

    "flood": {
        "China": ["洪水"],
        "Germany": ["Überschwemmung"],
        "Portugal": ["inundação"],
        "Japan": ["洪水"],
        "Spain": ["inundación"],
        "Romania": ["inundație"],
        "Thailand": ["น้ำท่วม"],
        "South Korea": ["홍수"]
    },

    "factory_fire": {
        "China": ["工厂火灾"],
        "Germany": ["Fabrikbrand"],
        "Portugal": ["incêndio"],
        "Japan": ["工場火災"],
        "Spain": ["incendio"],
        "Romania": ["incendiu"],
        "Thailand": ["ไฟไหม้โรงงาน"],
        "South Korea": ["공장 화재"]
    },

    "strike": {
        "China": ["罢工"],
        "Germany": ["Streik"],
        "Portugal": ["greve"],
        "Japan": ["ストライキ"],
        "Spain": ["huelga"],
        "Romania": ["grevă"],
        "Thailand": ["หยุดงาน"],
        "South Korea": ["파업"]
    },

    "power_outage": {
        "China": ["停电"],
        "Germany": ["Stromausfall"],
        "Portugal": ["apagão"],
        "Japan": ["停電"],
        "Spain": ["apagón"],
        "Romania": ["pană de curent"],
        "Thailand": ["ไฟฟ้าดับ"],
        "South Korea": ["정전"]
    },

    "production_shutdown": {
        "China": ["停产"],
        "Germany": ["Produktionsstopp"],
        "Portugal": ["paralisação"],
        "Japan": ["生産停止"],
        "Spain": ["parada de producción"],
        "Romania": ["oprire producție"],
        "Thailand": ["หยุดการผลิต"],
        "South Korea": ["생산중단"]
    },

    "port_disruption": {
        "China": ["港口拥堵"],
        "Germany": ["Hafenstörung"],
        "Portugal": ["congestionamento portuário"],
        "Japan": ["港湾混雑"],
        "Spain": ["congestión portuaria"],
        "Romania": ["congestie portuară"],
        "Thailand": ["ท่าเรือแออัด"],
        "South Korea": ["항만 차질"]
    }
}


# =========================
# 쿼리 생성
# =========================

def build_query(country, risk):

    local_country = COUNTRIES[country]["local"]
    language = COUNTRIES[country]["lang"]

    risk_keywords = RISKS[risk][country]

    risk_query = " OR ".join(
        [f'"{x}"' for x in risk_keywords]
    )

    # AND 넣지 말 것 (GDELT 오류 방지)
    query = f'("{local_country}" OR "{country}") ({risk_query}) sourcelang:{language}'

    return query


# =========================
# GDELT 검색
# =========================

def search_gdelt(query):

    url = "https://api.gdeltproject.org/api/v2/doc/doc"

    params = {
        "query": query,
        "mode": "artlist",
        "format": "json",
        "maxrecords": 10,
        "timespan": "7d",
        "sort": "datedesc"
    }

    for retry in range(3):

        try:

            response = requests.get(
                url,
                params=params,
                timeout=20
            )

            # 요청 많으면 대기
            if response.status_code == 429:

                wait_time = 10 * (retry + 1)

                print(f"429 발생 → {wait_time}초 대기")

                time.sleep(wait_time)

                continue

            if response.status_code != 200:

                print("HTTP ERROR:", response.status_code)

                return []

            try:
                data = response.json()

            except:
                print("JSON 파싱 실패")
                print(response.text[:300])
                return []

            return data.get("articles", [])

        except Exception as e:

            print("요청 실패:", e)

            time.sleep(5)

    return []


# =========================
# 전체 실행
# =========================

def run_monitoring():

    all_results = []

    for country in COUNTRIES:

        for risk in RISKS:

            print(f"\n검색 중: {country} / {risk}")

            query = build_query(country, risk)

            print(query)

            articles = search_gdelt(query)

            for article in articles:

                all_results.append({

                    "country": country,
                    "risk_type": risk,
                    "query": query,

                    "title": article.get("title"),
                    "url": article.get("url"),
                    "domain": article.get("domain"),
                    "seendate": article.get("seendate")
                })

            # rate limit 방지
            time.sleep(5)

    return all_results


# =========================
# JSON 저장
# =========================

if __name__ == "__main__":

    results = run_monitoring()

    output = {

        "created_at": datetime.now().isoformat(),

        "total_count": len(results),

        "results": results
    }

    with open(
        "gdelt_results.json",
        "w",
        encoding="utf-8"
    ) as f:

        json.dump(
            output,
            f,
            ensure_ascii=False,
            indent=2
        )

    print("\n완료")
    print(f"총 기사 수: {len(results)}")
