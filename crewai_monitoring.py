import os
import json
import time
import re
from datetime import datetime

import trafilatura
from dotenv import load_dotenv
from crewai import Agent, Task, Crew, Process, LLM

load_dotenv()

INPUT_FILE = "gdelt_results.json"
OUTPUT_FILE = "crewai_results.json"

# LLM 설정
llm = LLM(
    model="gpt-4o-mini",
    api_key=os.getenv("OPENAI_API_KEY"),
    temperature=0
)

# Agent 1 (Disruption Monitoring Agent) 설정 - 논문 Appendix A2 완벽 대응
risk_analyzer = Agent(
    role="Disruption Monitoring Agent",
    goal="Systematically analyse news articles, identify the supply chain disruption type, extract affected entities, and formulate structured risk questions for Knowledge Graph traversal.",
    backstory="""
    You are a top-tier expert in supply chain risk management, working in a company specialising in disruptions,
    ripple effects, and industry interdependencies. You have extensive experience analyzing global events and mapping
    disruptions to supply chains across tiers. Your task is to act as Agent 1 in the multi-agent pipeline, converting 
    unstructured news articles into structured disruption intelligence and diagnostic queries for downstream Agent 2.
    """,
    llm=llm,
    verbose=True
)


def load_gdelt_results() -> list:
    """GDELT 수집 결과 JSON을 로드합니다."""
    if not os.path.exists(INPUT_FILE):
        print(f"[ERROR] {INPUT_FILE} 파일이 없습니다.")
        return []

    with open(INPUT_FILE, "r", encoding="utf-8") as f:
        data = json.load(f)

    if isinstance(data, list):
        return data
    if isinstance(data, dict):
        return data.get("results", data.get("articles", []))
    return []


def extract_url(article: dict) -> str:
    """기사 객체에서 URL을 추출합니다."""
    for key in ["url", "link", "source_url"]:
        if article.get(key):
            return article[key]
    return ""


def extract_title(article: dict) -> str:
    """기사 객체에서 제목을 추출합니다."""
    for key in ["title", "headline"]:
        if article.get(key):
            return article[key]
    return ""


def extract_article_text(url: str) -> str:
    """Trafilatura를 사용해 웹 페이지 본문을 추출합니다."""
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
        print(f"[WARN] 본문 추출 실패: {url} | {e}")
        return ""


def parse_json_from_response(raw: str) -> dict | None:
    """LLM의 응답에서 JSON 구조를 안전하게 추출합니다."""
    cleaned = re.sub(r"```(?:json)?", "", raw).replace("```", "").strip()

    try:
        return json.loads(cleaned)
    except json.JSONDecodeError:
        pass

    match = re.search(r"\{.*\}", cleaned, re.DOTALL)
    if match:
        try:
            return json.loads(match.group())
        except json.JSONDecodeError:
            pass

    return None


def analyze_article_with_crewai(article: dict) -> dict | None:
    """논문 Agent 1 스키마 규격에 맞춰 뉴스 기사를 정밀 분석합니다."""
    title = extract_title(article)
    url = extract_url(article)

    if not url:
        return None

    body = extract_article_text(url) or title
    body = body[:4000]

    # 논문 Appendix A2 및 Figure 4 / Figure 8 스키마 반영 프롬프트
    task = Task(
        description=f"""
Carefully read and analyze the following news article from a supply chain risk management perspective.

Article Title: {title}
URL: {url}
Content:
{body}

Instructions:
1. Determine whether this article describes an actual supply chain disruption (is_supply_chain_disruption: true/false).
2. Classify the disruption_type: "Geopolitical", "Trade Policy", "Natural Disaster", "Company Bankruptcy", "Operation", "Logistics", "Energy", or "Other".
3. Extract all impacted elements into separate lists:
   - companies_involved: Specific companies mentioned or directly impacted.
   - industries_involved: Specific industries impacted (e.g., Automotive, Semiconductors, Energy, Mining).
   - countries_involved: Specific countries or regions affected.
4. Formulate logical, structured supply chain risk exposure check questions (risk_exposure_questions) for Agent 2 (Knowledge Graph Query Agent) to trace multi-tier supplier paths (e.g., "Which of Tier-1 suppliers are located in Russia or Ukraine?").
5. Provide a clear reasoning statement and a concise 2-3 sentence summary.

Return ONLY a valid raw JSON object matching the exact format below, with NO markdown formatting or commentary:

{{
  "is_supply_chain_disruption": true,
  "disruption_type": "Geopolitical | Natural Disaster | Trade Policy | Operation | Logistics | Energy | Other",
  "event": "Specific event name (e.g., Russia-Ukraine War)",
  "companies_involved": ["Company A", "Company B"],
  "industries_involved": ["Industry A", "Industry B"],
  "countries_involved": ["Country A", "Country B"],
  "risk_exposure_questions": [
    "Question for Knowledge Graph Query Agent 1",
    "Question for Knowledge Graph Query Agent 2"
  ],
  "reason": "Detailed expert reasoning on why this impacts supply chains.",
  "summary": "Executive summary of the article in 2-3 sentences."
}}
""",
        expected_output="Paper-compliant Agent 1 Disruption Monitoring JSON Output",
        agent=risk_analyzer
    )

    crew = Crew(
        agents=[risk_analyzer],
        tasks=[task],
        process=Process.sequential,
        verbose=True
    )

    try:
        result = crew.kickoff()
        raw_output = str(result)

        parsed = parse_json_from_response(raw_output)

        # JSON 파싱 실패 시 적용할 Fallback (동일 논문 규격 스키마 유지)
        if parsed is None:
            print(f"[WARN] JSON 파싱 실패 → fallback 적용: {title}")
            return {
                "title": title,
                "url": url,
                "is_supply_chain_disruption": False,
                "disruption_type": "Other",
                "event": "unknown",
                "companies_involved": [],
                "industries_involved": [],
                "countries_involved": [],
                "risk_exposure_questions": [],
                "reason": "CrewAI output was not valid JSON.",
                "summary": raw_output[:500]
            }

        # 메타데이터 추가
        parsed["title"] = title
        parsed["url"] = url
        return parsed

    except Exception as e:
        print(f"[ERROR] CrewAI 분석 실패: {title} | {e}")
        return None


def main():
    articles = load_gdelt_results()
    print(f"불러온 기사 수: {len(articles)}")

    existing_output = {}
    analyzed_urls = set()

    if os.path.exists(OUTPUT_FILE):
        try:
            with open(OUTPUT_FILE, "r", encoding="utf-8") as f:
                existing_output = json.load(f)

            for item in existing_output.get("results", []):
                if item.get("url"):
                    analyzed_urls.add(item["url"])

            print(f"기존 분석 결과: {len(analyzed_urls)}건 → 스킵 예정")

        except Exception:
            existing_output = {}

    previous_results = existing_output.get("results", [])
    new_results = []

    for i, article in enumerate(articles, start=1):
        url = extract_url(article)
        title = extract_title(article)

        if url in analyzed_urls:
            print(f"[SKIP] {title}")
            continue

        print("=" * 50)
        print(f"{i}번째 기사 CrewAI 분석: {title}")

        analyzed = analyze_article_with_crewai(article)

        if analyzed:
            new_results.append(analyzed)
            analyzed_urls.add(url)

        time.sleep(2)

    all_results = previous_results + new_results

    output = {
        "created_at": datetime.now().isoformat(),
        "input_file": INPUT_FILE,
        "total_input_articles": len(articles),
        "total_analyzed_articles": len(all_results),
        "new_analyzed_articles": len(new_results),
        "results": all_results
    }

    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        json.dump(output, f, ensure_ascii=False, indent=2)

    print(f"\n저장 완료: {OUTPUT_FILE}")
    print(f"신규 분석: {len(new_results)}건 / 누적: {len(all_results)}건")


if __name__ == "__main__":
    main()
