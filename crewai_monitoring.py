import os
import json
import time
import re
from datetime import datetime

import trafilatura
from openai import OpenAI
from dotenv import load_dotenv

load_dotenv()

INPUT_FILE = "gdelt_results.json"
OUTPUT_FILE = "crewai_results.json"

# ✅ FIX: OpenAI 클라이언트를 모듈 레벨에서 한 번만 초기화
#         이전 코드는 crewai의 Agent/Task/Crew를 기사마다 새로 생성하는 구조였음
#         → 매 기사마다 CrewAI 인스턴스를 생성해 불필요한 오버헤드 발생
#         → CrewAI는 내부적으로 OpenAI를 한 번 더 감싸는 구조라 JSON 파싱 실패가 잦음
#         → 직접 OpenAI chat.completions.create()로 교체해 안정성 확보
client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))

SYSTEM_PROMPT = """
당신은 글로벌 공급망 리스크 분석 전문가입니다.
뉴스 기사를 분석하여 공급망 disruption 여부와 리스크 유형을 판단합니다.

판단 기준:
- 공급망 관련: 자연재해, 공장 화재, 파업, 항만 차질, 정전, 생산 중단, 관세, 제재, 수출통제, 물류 지연, 에너지 부족
- 비관련: 단순 정치/사회 뉴스로 물류·공장·항만·생산·무역·에너지에 영향 없는 경우

반드시 아래 JSON 형식만 반환하세요. 마크다운, 코드블록, 설명 문장 없이 JSON만 출력하세요.

{
  "is_supply_chain_disruption": true,
  "risk_category": "disaster | operation | logistics | policy_regulation | energy | geopolitical | unknown",
  "event_type": "구체적 사건 유형",
  "affected_country": "영향 국가",
  "affected_location": "영향 지역",
  "severity_score": 3,
  "reason": "공급망과 관련 있다고 판단한 이유",
  "summary": "기사 요약 (2-3문장)"
}
""".strip()


def load_gdelt_results() -> list:
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
    for key in ["url", "link", "source_url"]:
        if article.get(key):
            return article[key]
    return ""


def extract_title(article: dict) -> str:
    for key in ["title", "headline"]:
        if article.get(key):
            return article[key]
    return ""


def extract_article_text(url: str) -> str:
    """trafilatura로 본문 추출. 실패 시 빈 문자열 반환"""
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
    """
    ✅ FIX: LLM 응답에서 JSON을 안전하게 파싱
    - 마크다운 코드블록(```json ... ```) 제거 후 파싱 시도
    - 실패 시 정규식으로 JSON 블록 추출 재시도
    """
    # 1차 시도: 마크다운 펜스 제거 후 직접 파싱
    cleaned = re.sub(r"```(?:json)?", "", raw).replace("```", "").strip()
    try:
        return json.loads(cleaned)
    except json.JSONDecodeError:
        pass

    # 2차 시도: 정규식으로 {...} 블록 추출
    match = re.search(r"\{.*\}", cleaned, re.DOTALL)
    if match:
        try:
            return json.loads(match.group())
        except json.JSONDecodeError:
            pass

    return None


def analyze_article(article: dict) -> dict | None:
    title = extract_title(article)
    url = extract_url(article)

    if not url:
        return None

    # 본문 추출 (없으면 제목만 사용)
    body = extract_article_text(url) or title
    body = body[:4000]  # 토큰 절약

    user_prompt = f"""
제목: {title}
URL: {url}

기사 본문:
{body}
""".strip()

    try:
        # ✅ FIX: CrewAI 대신 OpenAI를 직접 호출
        #         CrewAI는 내부적으로 OpenAI를 다시 감싸고 JSON 파싱 실패가 잦아
        #         직접 호출이 훨씬 안정적
        response = client.chat.completions.create(
            model="gpt-4o-mini",   # 비용 대비 성능 최적
            temperature=0,         # 분류 작업이므로 결정론적 출력
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": user_prompt},
            ]
        )

        raw_output = response.choices[0].message.content or ""
        parsed = parse_json_from_response(raw_output)

        if parsed is None:
            # ✅ FIX: 파싱 실패 시 원본 텍스트를 summary에 보존하고 계속 진행
            print(f"[WARN] JSON 파싱 실패 → fallback 적용: {title}")
            return {
                "title": title,
                "url": url,
                "is_supply_chain_disruption": False,
                "risk_category": "unknown",
                "event_type": "unknown",
                "affected_country": "unknown",
                "affected_location": "unknown",
                "severity_score": 1,
                "reason": "LLM 출력이 유효한 JSON이 아닙니다.",
                "summary": raw_output[:500]
            }

        # title, url은 LLM이 아닌 실제 데이터로 덮어쓰기 (hallucination 방지)
        parsed["title"] = title
        parsed["url"] = url
        return parsed

    except Exception as e:
        print(f"[ERROR] OpenAI 호출 실패: {title} | {e}")
        return None


def main():
    articles = load_gdelt_results()
    print(f"불러온 기사 수: {len(articles)}")

    # ✅ FIX: 이미 분석된 URL 추적 → 재실행 시 중복 분석 방지
    existing_output = {}
    analyzed_urls: set[str] = set()

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

        # ✅ FIX: 이미 분석된 URL 스킵
        if url in analyzed_urls:
            print(f"[SKIP] {title}")
            continue

        print("=" * 50)
        print(f"{i}번째 기사 분석: {title}")

        analyzed = analyze_article(article)
        if analyzed:
            new_results.append(analyzed)
            analyzed_urls.add(url)

        time.sleep(1)  # ✅ FIX: CrewAI의 8초 → 직접 호출은 1초로 충분

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
