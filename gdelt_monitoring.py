import requests
import json
import time
from urllib.parse import urlencode
from datetime import datetime

# =========================
# 1. 국가별 설정
# =========================

COUNTRIES = {
    "China": {
        "local_name": "中国",
        "sourcelang": "chinese"
    },
    "Germany": {
        "local_name": "Deutschland",
        "sourcelang": "german"
    },
    "Portugal": {
        "local_name": "Portugal",
        "sourcelang": "portuguese"
    },
    "Japan": {
        "local_name": "日本",
        "sourcelang": "japanese"
    },
    "Spain": {
        "local_name": "España",
        "sourcelang": "spanish"
    },
    "Romania": {
        "local_name": "România",
        "sourcelang": "romanian"
    },
    "Thailand": {
        "local_name": "ประเทศไทย",
        "sourcelang": "thai"
    },
    "South Korea": {
        "local_name": "한국",
        "sourcelang": "korean"
    }
}

# =========================
# 2. 리스크별 현지어 키워드
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
        "China": ["洪水", "暴雨"],
        "Germany": ["Überschwemmung", "Hochwasser"],
        "Portugal": ["inundação", "cheia"],
        "Japan": ["洪水", "豪雨"],
        "Spain": ["inundación"],
        "Romania": ["inundație"],
        "Thailand": ["น้ำท่วม"],
        "South Korea": ["홍수", "침수"]
    },
    "factory_fire": {
        "China": ["工厂火灾", "火灾"],
        "Germany": ["Fabrikbrand", "Brand"],
        "Portugal": ["incêndio em fábrica", "incêndio"],
        "Japan": ["工場火災", "火災"],
        "Spain": ["incendio en fábrica", "incendio"],
        "Romania": ["incendiu la fabrică", "incendiu"],
        "Thailand": ["ไฟไหม้โรงงาน", "ไฟไหม้"],
        "South Korea": ["공장 화재", "화재"]
    },
    "strike": {
        "China": ["罢工"],
        "Germany": ["Streik"],
        "Portugal": ["greve"],
        "Japan": ["ストライキ"],
        "Spain": ["huelga"],
        "Romania": ["grevă"],
        "Thailand": ["การประท้วง", "หยุดงาน"],
        "South Korea": ["파업"]
    },
    "power_outage": {
        "China": ["停电", "限电"],
        "Germany": ["Stromausfall"],
        "Portugal": ["apagão", "falha de energia"],
        "Japan": ["停電", "電力不足"],
        "Spain": ["apagón", "corte de luz"],
        "Romania": ["pană de curent"],
        "Thailand": ["ไฟฟ้าดับ"],
        "South Korea": ["정전", "전력난"]
    },
    "production_shutdown": {
        "China": ["停产", "工厂停产"],
        "Germany": ["Produktionsstopp", "Fabrikstillstand"],
        "Portugal": ["paralisação da produção"],
        "Japan": ["生産停止", "工場停止"],
        "Spain": ["parada de producción"],
        "Romania": ["oprire producție"],
        "Thailand": ["หยุดการผลิต"],
        "South Korea": ["생산중단", "공장 가동 중단"]
    },
    "port_disruption": {
        "China": ["港口拥堵", "港口关闭"],
        "Germany": ["Hafenstörung", "Hafenstreik"],
        "Portugal": ["congestionamento portuário", "greve portuária"],
        "Japan": ["港湾混雑", "港湾停止"],
        "Spain": ["congestión portuaria", "huelga portuaria"],
        "Romania": ["congestie portuară"],
        "Thailand": ["ท่าเรือแออัด", "ท่าเรือหยุดชะงัก"],
        "South Korea": ["항만 혼잡", "항만 차질", "항만 파업"]
    }
}

# =========================
# 3. GDELT 검색 함수
# =========================

def build_query(country_name, country_info, risk_name):
    local_country = country_info["local_name"]
    sourcelang = country_info["sourcelang"]
    risk_keywords = RISKS[risk_name][country_name]

    risk_query = " OR ".join([f'"{kw}"' for kw in risk_keywords])

    query = f'("{local_country}" OR "{country_name}") AND ({risk_query}) sourcelang:{sourcelang}'
    return query


def search_gdelt(query, max_records=10, timespan="7d"):
    base_url = "https://api.gdeltproject.org/api/v2/doc/doc"

    params = {
        "query": query,
        "mode": "artlist",
        "format": "json",
        "maxrecords": max_records,
        "timespan": timespan,
        "sort": "datedesc"
    }

    url = base_url + "?" + urlencode(params)

    try:
        response = requests.get(url, timeout=20)
        response.raise_for_status()
        data = response.json()
        return data.get("articles", [])

    except Exception as e:
        print(f"[ERROR] {query}")
        print(e)
        return []


# =========================
# 4. 전체 실행
# =========================

def run_monitoring():
    results = []

    for country_name, country_info in COUNTRIES.items():
        for risk_name in RISKS.keys():
            query = build_query(country_name, country_info, risk_name)

            print(f"\n검색 중: {country_name} / {risk_name}")
            print(query)

            articles = search_gdelt(
                query=query,
                max_records=10,
                timespan="7d"
            )

            for article in articles:
                results.append({
                    "country": country_name,
                    "local_country_name": country_info["local_name"],
                    "risk_type": risk_name,
                    "query": query,
                    "title": article.get("title"),
                    "url": article.get("url"),
                    "domain": article.get("domain"),
                    "language": article.get("language"),
                    "source_country": article.get("sourcecountry"),
                    "seendate": article.get("seendate"),
                    "socialimage": article.get("socialimage")
                })

            time.sleep(1)

    return results


# =========================
# 5. JSON 저장
# =========================

if __name__ == "__main__":
    gdelt_results = run_monitoring()

    output = {
        "created_at": datetime.now().isoformat(),
        "description": "GDELT supply chain risk monitoring results",
        "countries": list(COUNTRIES.keys()),
        "risk_types": list(RISKS.keys()),
        "total_results": len(gdelt_results),
        "results": gdelt_results
    }

    with open("gdelt_supply_chain_risk_results.json", "w", encoding="utf-8") as f:
        json.dump(output, f, ensure_ascii=False, indent=2)

    print("\n완료")
    print(f"총 수집 기사 수: {len(gdelt_results)}")
    print("저장 파일: gdelt_supply_chain_risk_results.json")
