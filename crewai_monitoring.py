import os
import json
import time
from datetime import datetime

import trafilatura
from crewai import Agent, Task, Crew, Process


INPUT_FILE = "gdelt_results.json"
OUTPUT_FILE = "crewai_results.json"


def load_gdelt_results():
    if not os.path.exists(INPUT_FILE):
        print(f"{INPUT_FILE} 파일이 없습니다.")
        return []

    with open(INPUT_FILE, "r", encoding="utf-8") as f:
        data = json.load(f)

    if isinstance(data, list):
        return data

    if isinstance(data, dict):
        if "results" in data:
            return data["results"]
        if "articles" in data:
            return data["articles"]

    return []


def extract_url(article):
    possible_keys = ["url", "link", "source_url"]
    for key in possible_keys:
        if key in article and article[key]:
            return article[key]
    return ""


def extract_title(article):
    possible_keys = ["title", "headline"]
    for key in possible_keys:
        if key in article and article[key]:
            return article[key]
    return ""


def extract_article_text(url):
    try:
        downloaded = trafilatura.fetch_url(url)

        if downloaded is None:
            return ""

        text = trafilatura.extract(
            downloaded,
            include_comments=False,
            include_tables=False
        )

        return text or ""

    except Exception as e:
        print(f"본문 추출 실패: {url}")
        print(e)
        return ""


def analyze_article_with_crewai(article):
    title = extract_title(article)
    url = extract_url(article)

    if not url:
        return None

    body = extract_article_text(url)

    if not body:
        body = title

    body = body[:4000]

    analyst = Agent(
        role="Supply Chain Disruption Analyst",
        goal="뉴스 기사가 공급망 disruption과 관련 있는지 판단하고 구조화된 JSON으로 정리한다.",
        backstory=(
            "당신은 글로벌 공급망 리스크 분석가입니다. "
            "자연재해, 공장 화재, 파업, 항만 차질, 정전, 생산 중단, 관세, 제재, 수출통제, "
            "물류 지연, 에너지 부족 등이 제조업 공급망에 미치는 영향을 분석합니다."
        ),
        verbose=True
    )

    task = Task(
        description=f"""
다음 뉴스 기사를 분석하세요.

제목:
{title}

URL:
{url}

기사 본문:
{body}

판단 기준:
1. 공급망 disruption과 관련 있으면 true
2. 단순 정치/사회 뉴스이고 물류, 공장, 항만, 생산, 무역, 에너지, 운송 영향이 없으면 false
3. 관련이 있다면 리스크 유형을 분류하세요.

리스크 유형:
- disaster
- operation
- logistics
- policy_regulation
- energy
- geopolitical
- unknown

반드시 아래 JSON 형식만 출력하세요. 설명 문장이나 마크다운은 쓰지 마세요.

{{
  "title": "{title}",
  "url": "{url}",
  "is_supply_chain_disruption": true,
  "risk_category": "disaster | operation | logistics | policy_regulation | energy | geopolitical | unknown",
  "event_type": "구체적 사건 유형",
  "affected_country": "영향 국가",
  "affected_location": "영향 지역",
  "severity_score": 1,
  "reason": "공급망과 관련 있다고 판단한 이유",
  "summary": "기사 요약"
}}
""",
        expected_output="Valid JSON object only.",
        agent=analyst
    )

    crew = Crew(
        agents=[analyst],
        tasks=[task],
        process=Process.sequential,
        verbose=True
    )

    result = crew.kickoff()

    try:
        parsed = json.loads(str(result))
        return parsed

    except Exception:
        return {
            "title": title,
            "url": url,
            "is_supply_chain_disruption": False,
            "risk_category": "unknown",
            "event_type": "unknown",
            "affected_country": "unknown",
            "affected_location": "unknown",
            "severity_score": 1,
            "reason": "CrewAI output was not valid JSON.",
            "summary": str(result)
        }


def main():
    articles = load_gdelt_results()

    print(f"불러온 기사 수: {len(articles)}")

    results = []

    for i, article in enumerate(articles[:10], start=1):
        print("=" * 50)
        print(f"{i}번째 기사 분석 중")
        print(extract_title(article))

        analyzed = analyze_article_with_crewai(article)

        if analyzed:
            results.append(analyzed)

        time.sleep(8)

    output = {
        "created_at": datetime.now().isoformat(),
        "input_file": INPUT_FILE,
        "total_input_articles": len(articles),
        "total_analyzed_articles": len(results),
        "results": results
    }

    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        json.dump(output, f, ensure_ascii=False, indent=2)

    print(f"저장 완료: {OUTPUT_FILE}")


if __name__ == "__main__":
    main()
