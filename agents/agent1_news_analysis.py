import os
import json
import time
import re
from pathlib import Path

import trafilatura
from dotenv import load_dotenv
from crewai import Agent, Task, Crew, Process, LLM


# =========================================================
# 1. 기본 설정
# =========================================================

# 현재 파일 위치:
# supply-chain/agents/agent1_news_analysis.py
#
# 부모 폴더:
# supply-chain/agents
#
# 부모의 부모:
# supply-chain
BASE_DIR = Path(__file__).resolve().parent.parent

GDELT_INPUT_FILE = BASE_DIR / "gdelt_results.json"
NEWSAPI_INPUT_FILE = BASE_DIR / "newsapi_results.json"
OUTPUT_FILE = BASE_DIR / "agent1_results.json"
# NEWS_SOURCE_MODE: "both" (default), "gdelt", or "newsapi"
NEWS_SOURCE_MODE = os.getenv("NEWS_SOURCE_MODE", "both").strip().lower()


# .env 파일이 있다면 로드
load_dotenv(BASE_DIR / ".env")


# =========================================================
# 2. OpenAI LLM 설정
# =========================================================

llm = LLM(
    model="gpt-4o-mini",
    api_key=os.getenv("OPENAI_API_KEY"),
    temperature=0
)


# =========================================================
# 3. Agent 1 정의
# =========================================================

risk_analyzer = Agent(
    role="Supply Chain Disruption Monitoring Agent",

    goal=(
        "Analyze news articles and identify whether they represent "
        "a supply chain disruption. Extract the disruption type, "
        "companies, industries, countries, and formulate risk exposure "
        "questions that can be used by Agent 2 for Knowledge Graph analysis."
    ),

    backstory="""
    You are an expert in supply chain risk management and global
    supply chain disruption monitoring.

    Your role is Agent 1 in a multi-agent supply chain risk management
    system.

    You analyze unstructured news articles and convert them into
    structured disruption information for downstream agents.

    You must focus on actual or potential impacts on supply chains,
    including suppliers, manufacturers, logistics, ports, production,
    trade, energy, natural disasters, geopolitical events, and
    regulatory changes.

    Do not assume that every company-related or economic news article
    is a supply chain disruption.

    Only classify an article as a supply chain disruption when there
    is a reasonable connection to supply, production, transportation,
    logistics, trade, sourcing, manufacturing, or other supply-chain
    activities.
    """,

    llm=llm,
    verbose=True
)


# =========================================================
# 4. 뉴스 수집 결과 불러오기 (GDELT + NewsAPI.ai)
# =========================================================

def load_news_file(filepath: Path, source_name: str) -> list:
    """
    수집기 JSON의 {"results": [...]} 또는 리스트 형식을 읽는다.
    파일이 없거나 읽을 수 없어도 다른 뉴스 소스 처리는 계속한다.
    """
    if not filepath.exists():
        print(f"[INFO] {source_name} 입력 파일이 없습니다: {filepath}")
        return []

    try:
        with open(filepath, "r", encoding="utf-8") as f:
            data = json.load(f)

        if isinstance(data, dict):
            articles = data.get("results", [])
        elif isinstance(data, list):
            articles = data
        else:
            articles = []

        if not isinstance(articles, list):
            print(f"[WARN] {source_name}의 results가 리스트가 아닙니다.")
            return []

        normalized = []
        for article in articles:
            if not isinstance(article, dict):
                continue
            item = dict(article)
            item.setdefault("source_api", source_name)
            # 수집 파일 이름을 기준으로 출처를 보정한다.
            if not item.get("source_api"):
                item["source_api"] = source_name
            normalized.append(item)

        print(f"[INFO] {source_name}: {len(normalized)}건 로드")
        return normalized

    except (OSError, json.JSONDecodeError) as e:
        print(f"[ERROR] {source_name} 결과 로드 실패: {e}")
        return []


def load_all_news_results() -> list:
    """
    NEWS_SOURCE_MODE 설정에 따라 GDELT, NewsAPI.ai 또는 두 소스를 읽는다.
    기본값은 기존 동작과의 호환성을 위해 both이다.
    """
    combined = []
    seen_urls = set()

    source_map = {
        "both": [
            (GDELT_INPUT_FILE, "gdelt"),
            (NEWSAPI_INPUT_FILE, "newsapi.ai"),
        ],
        "gdelt": [
            (GDELT_INPUT_FILE, "gdelt"),
        ],
        "newsapi": [
            (NEWSAPI_INPUT_FILE, "newsapi.ai"),
        ],
        "newsapi.ai": [
            (NEWSAPI_INPUT_FILE, "newsapi.ai"),
        ],
    }
    sources = source_map.get(NEWS_SOURCE_MODE)
    if sources is None:
        raise ValueError(
            f"잘못된 NEWS_SOURCE_MODE={NEWS_SOURCE_MODE!r}. "
            "가능한 값: both, gdelt, newsapi"
        )

    print(f"[INFO] 뉴스 소스 모드: {NEWS_SOURCE_MODE}")

    for filepath, source_name in sources:
        for article in load_news_file(filepath, source_name):
            url = str(article.get("url", "") or "").strip()
            if not url:
                continue
            if url in seen_urls:
                continue
            seen_urls.add(url)
            article["url"] = url
            combined.append(article)

    print(f"[INFO] 통합 뉴스 수: {len(combined)}건")
    return combined


# =========================================================
# 5. 기존 Agent 1 결과 불러오기
# =========================================================

def load_existing_results():
    """
    기존 agent1_results.json을 불러온다.

    이미 분석한 뉴스 URL은 다시 분석하지 않기 위해 사용한다.
    """

    if not OUTPUT_FILE.exists():
        return [], set()

    try:
        with open(OUTPUT_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)

        if isinstance(data, dict):
            results = data.get("results", [])
        elif isinstance(data, list):
            results = data
        else:
            results = []

        existing_urls = {
            item.get("url")
            for item in results
            if item.get("url")
        }

        return results, existing_urls

    except Exception as e:
        print(f"[WARN] 기존 Agent 1 결과 로드 실패: {e}")
        return [], set()


# =========================================================
# 6. 뉴스 URL에서 본문 추출
# =========================================================

def extract_article_text(url: str) -> str:
    """
    뉴스 URL에서 기사 본문을 추출한다.

    본문 추출에 실패하면 빈 문자열을 반환한다.
    """

    if not url:
        return ""

    try:
        downloaded = trafilatura.fetch_url(url)

        if not downloaded:
            return ""

        text = trafilatura.extract(
            downloaded,
            include_comments=False,
            include_tables=False
        )

        return text or ""

    except Exception as e:
        print(f"[WARN] 기사 본문 추출 실패: {url}")
        print(f"       {e}")
        return ""


# =========================================================
# 7. JSON 파싱
# =========================================================

def parse_json_from_response(raw_response: str):
    """
    CrewAI가 반환한 문자열에서 JSON을 추출한다.
    """

    if not raw_response:
        return None

    text = raw_response.strip()

    # Markdown code block 제거
    text = re.sub(
        r"^```(?:json)?\s*",
        "",
        text,
        flags=re.IGNORECASE
    )

    text = re.sub(
        r"\s*```$",
        "",
        text
    )

    # 먼저 전체 문자열을 JSON으로 시도
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass

    # 문자열 안에서 {...} 부분 찾기
    match = re.search(r"\{.*\}", text, re.DOTALL)

    if match:
        json_text = match.group(0)

        try:
            return json.loads(json_text)
        except json.JSONDecodeError:
            pass

    return None


# =========================================================
# 8. Agent 1 뉴스 분석
# =========================================================

def analyze_article_with_agent1(article):
    """
    하나의 뉴스 기사를 Agent 1이 분석한다 (GDELT 또는 NewsAPI.ai).
    """

    title = article.get("title", "")
    url = article.get("url", "")

    print("\n" + "=" * 80)
    print("Agent 1 analyzing:")
    print(title)
    print("=" * 80)

    # -----------------------------------------------------
    # 기사 본문 추출
    # -----------------------------------------------------

    article_text = extract_article_text(url)

    # 본문 추출 실패 시 제목을 사용
    if not article_text:
        article_text = title

    # 너무 긴 기사 방지
    article_text = article_text[:5000]

    # -----------------------------------------------------
    # Agent 1 Task
    # -----------------------------------------------------

    task_description = f"""
    Analyze the following news article as Agent 1 of a
    supply chain risk monitoring system.

    =========================
    NEWS ARTICLE
    =========================

    Title:
    {title}

    URL:
    {url}

    Article:
    {article_text}

    =========================
    TASK
    =========================

    Determine whether this article describes an actual or potential
    supply chain disruption.

    You must produce the following information.

    1. is_supply_chain_disruption

    Set this to true only when the event has a meaningful connection
    to supply chain activities such as:

    - suppliers
    - manufacturing
    - production
    - logistics
    - transportation
    - ports
    - trade
    - sourcing
    - energy supply
    - geopolitical restrictions
    - natural disasters affecting operations
    - labor disruptions
    - regulatory restrictions

    Otherwise set it to false.

    2. disruption_type

    Select one of:

    - Geopolitical
    - Trade Policy
    - Natural Disaster
    - Company Bankruptcy
    - Operation
    - Logistics
    - Energy
    - Other

    3. event

    Give a short and specific name for the disruption event.

    4. companies_involved

    Extract companies that are directly involved in the event
    or potentially exposed to it.

    5. industries_involved

    Extract industries directly affected by the event.

    6. countries_involved

    Extract countries directly involved in the event.

    7. risk_exposure_questions

    Create questions that Agent 2 can use to investigate the
    company's Knowledge Graph.

    These questions should focus on:

    - Which suppliers may be affected?
    - Which manufacturing or production relationships may be affected?
    - Which countries or regions create exposure?
    - Which supply-chain dependencies could transmit the disruption?
    - Which downstream companies or operations may be exposed?

    Do NOT simply repeat the news article.

    The questions should be useful for Knowledge Graph traversal.

    Example:

    "Which suppliers of Company A operate in the affected region?"

    "Which manufacturing facilities depend on suppliers located
    in the affected country?"

    "Which downstream companies depend on products from the
    affected supplier?"

    8. reason

    Explain why this event should or should not be considered
    a supply chain disruption.

    9. summary

    Provide a concise 2-3 sentence executive summary.

    =========================
    OUTPUT FORMAT
    =========================

    Return ONLY valid JSON.

    Do not use Markdown.

    Use exactly this structure:

    {{
        "is_supply_chain_disruption": true,
        "disruption_type": "Natural Disaster",
        "event": "Specific event name",
        "companies_involved": [
            "Company A"
        ],
        "industries_involved": [
            "Automotive"
        ],
        "countries_involved": [
            "Japan"
        ],
        "risk_exposure_questions": [
            "Which suppliers of Company A operate in the affected region?",
            "Which downstream operations depend on the affected supplier?"
        ],
        "reason": "Explanation of the supply chain impact.",
        "summary": "A concise 2-3 sentence summary."
    }}
    """

    task = Task(
        description=task_description,
        expected_output="A valid JSON object containing the requested Agent 1 fields.",
        agent=risk_analyzer
    )

    # -----------------------------------------------------
    # Crew 실행
    # -----------------------------------------------------

    crew = Crew(
        agents=[risk_analyzer],
        tasks=[task],
        process=Process.sequential,
        verbose=True
    )

    try:
        result = crew.kickoff()

        raw_response = str(result)

        parsed_result = parse_json_from_response(raw_response)

        # -------------------------------------------------
        # JSON 파싱 실패
        # -------------------------------------------------

        if parsed_result is None:
            print("[ERROR] Agent 1 JSON parsing failed.")

            return {
                "is_supply_chain_disruption": False,
                "disruption_type": "Other",
                "event": "",
                "companies_involved": [],
                "industries_involved": [],
                "countries_involved": [],
                "risk_exposure_questions": [],
                "reason": "Agent 1 response could not be parsed as JSON.",
                "summary": "",
                "title": title,
                "url": url
            }

        # -------------------------------------------------
        # 필수 필드 보정
        # -------------------------------------------------

        parsed_result.setdefault(
            "is_supply_chain_disruption",
            False
        )

        parsed_result.setdefault(
            "disruption_type",
            "Other"
        )

        parsed_result.setdefault(
            "event",
            ""
        )

        parsed_result.setdefault(
            "companies_involved",
            []
        )

        parsed_result.setdefault(
            "industries_involved",
            []
        )

        parsed_result.setdefault(
            "countries_involved",
            []
        )

        parsed_result.setdefault(
            "risk_exposure_questions",
            []
        )

        parsed_result.setdefault(
            "reason",
            ""
        )

        parsed_result.setdefault(
            "summary",
            ""
        )

        # 원본 뉴스 정보 추가
        parsed_result["title"] = title
        parsed_result["url"] = url

        # 수집기와 무관한 공통 메타데이터 보존
        parsed_result["source_api"] = article.get("source_api", "")
        parsed_result["risk_type"] = article.get("risk_type", "")
        parsed_result["country"] = article.get("country", "")
        parsed_result["keyword"] = article.get("keyword", "")
        parsed_result["query"] = article.get("query", "")
        parsed_result["domain"] = article.get("domain", "")
        parsed_result["language"] = article.get("language", "")
        parsed_result["source_country"] = article.get("source_country", "")
        parsed_result["published_at"] = article.get("published_at", "")
        parsed_result["collected_at"] = article.get("collected_at", "")

        # 기존 Agent 2/후속 코드와의 호환성을 위해 레거시 필드도 유지.
        # NewsAPI.ai 기사에도 같은 메타데이터 값을 넣어 기존 필드 참조를 깨뜨리지 않는다.
        parsed_result["gdelt_risk_type"] = article.get("risk_type", "")
        parsed_result["gdelt_country"] = article.get("country", "")
        parsed_result["gdelt_keyword"] = article.get("keyword", "")

        return parsed_result

    except Exception as e:

        print(f"[ERROR] Agent 1 analysis failed: {e}")

        return {
            "is_supply_chain_disruption": False,
            "disruption_type": "Other",
            "event": "",
            "companies_involved": [],
            "industries_involved": [],
            "countries_involved": [],
            "risk_exposure_questions": [],
            "reason": f"Agent 1 execution failed: {str(e)}",
            "summary": "",
            "title": title,
            "url": url
        }


# =========================================================
# 9. 결과 저장
# =========================================================

def save_results(results):
    """
    Agent 1 분석 결과를 agent1_results.json으로 저장한다.
    """

    output = {
        "updated_at": time.strftime(
            "%Y-%m-%dT%H:%M:%SZ",
            time.gmtime()
        ),
        "total_count": len(results),
        "results": results
    }

    with open(
        OUTPUT_FILE,
        "w",
        encoding="utf-8"
    ) as f:

        json.dump(
            output,
            f,
            ensure_ascii=False,
            indent=2
        )

    print("\n" + "=" * 80)
    print("Agent 1 results saved.")
    print(f"File: {OUTPUT_FILE}")
    print(f"Total: {len(results)}")
    print("=" * 80)


# =========================================================
# 10. Main
# =========================================================

def main():

    print("\n")
    print("=" * 80)
    print(f"AGENT 1 - SUPPLY CHAIN NEWS ANALYSIS (source={NEWS_SOURCE_MODE})")
    print("=" * 80)

    # -----------------------------------------------------
    # GDELT + NewsAPI.ai 결과 불러오기
    # -----------------------------------------------------

    news_articles = load_all_news_results()
    print(f"Input articles (deduplicated): {len(news_articles)}")

    # -----------------------------------------------------
    # 기존 Agent 1 결과
    # -----------------------------------------------------

    existing_results, existing_urls = load_existing_results()

    if not news_articles:
        print("[INFO] 분석할 뉴스가 없습니다.")
        # downstream workflow가 사용할 결과 파일을 항상 유지
        save_results(existing_results)
        return


    print(
        f"Already analyzed: {len(existing_results)}"
    )

    # -----------------------------------------------------
    # 새로운 기사만 분석
    # -----------------------------------------------------

    new_articles = []

    for article in news_articles:

        url = article.get("url", "")

        if not url:
            continue

        if url in existing_urls:
            continue

        new_articles.append(article)

    print(
        f"New articles to analyze: {len(new_articles)}"
    )

    if not new_articles:
        print("[INFO] 새로 분석할 뉴스가 없습니다.")
        # 새 뉴스가 없어도 기존 결과를 다시 저장
        # -> agent1_results.json이 항상 존재하도록 보장
        save_results(existing_results)
        return

    # -----------------------------------------------------
    # Agent 1 실행
    # -----------------------------------------------------

    new_results = []

    for index, article in enumerate(
        new_articles,
        start=1
    ):

        print("\n")
        print(
            f"[{index}/{len(new_articles)}] "
            f"Processing article..."
        )

        result = analyze_article_with_agent1(article)

        new_results.append(result)

        # API 요청 간격
        time.sleep(2)

    # -----------------------------------------------------
    # 기존 + 신규 결과
    # -----------------------------------------------------

    all_results = existing_results + new_results

    save_results(all_results)

    # -----------------------------------------------------
    # 통계
    # -----------------------------------------------------

    disruption_count = sum(
        1
        for item in all_results
        if item.get("is_supply_chain_disruption") is True
    )

    print("\n")
    print("=" * 80)
    print("AGENT 1 COMPLETE")
    print("=" * 80)

    print(f"New analyzed       : {len(new_results)}")
    print(f"Total analyzed     : {len(all_results)}")
    print(f"Supply disruptions : {disruption_count}")
    print("=" * 80)


# =========================================================
# 실행
# =========================================================

if __name__ == "__main__":
    main()

