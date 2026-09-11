```python
import os
import json
from pathlib import Path
from datetime import datetime

from dotenv import load_dotenv
from neo4j import GraphDatabase


# ============================================================
# 1. 경로 설정
# ============================================================

BASE_DIR = Path(__file__).resolve().parent.parent

INPUT_FILE = BASE_DIR / "agent1_results.json"
OUTPUT_FILE = BASE_DIR / "agent2_results.json"

# .env 로드
load_dotenv(BASE_DIR / ".env")


# ============================================================
# 2. Neo4j 설정
# ============================================================

NEO4J_URI = os.getenv("NEO4J_URI")
NEO4J_USERNAME = os.getenv("NEO4J_USERNAME")
NEO4J_PASSWORD = os.getenv("NEO4J_PASSWORD")

if not NEO4J_URI:
    raise ValueError("NEO4J_URI가 .env에 설정되어 있지 않습니다.")

if not NEO4J_USERNAME:
    raise ValueError("NEO4J_USERNAME이 .env에 설정되어 있지 않습니다.")

if not NEO4J_PASSWORD:
    raise ValueError("NEO4J_PASSWORD가 .env에 설정되어 있지 않습니다.")


driver = GraphDatabase.driver(
    NEO4J_URI,
    auth=(NEO4J_USERNAME, NEO4J_PASSWORD)
)


# ============================================================
# 3. Agent 1 JSON 읽기
# ============================================================

def load_agent1_results():

    if not INPUT_FILE.exists():
        raise FileNotFoundError(
            f"Agent 1 결과 파일이 없습니다: {INPUT_FILE}"
        )

    with open(INPUT_FILE, "r", encoding="utf-8") as f:
        data = json.load(f)

    # Agent 1 결과가 리스트인 경우
    if isinstance(data, list):
        return data

    # {"results": [...]} 형태인 경우
    if isinstance(data, dict):
        return data.get("results", [])

    return []


# ============================================================
# 4. 문자열 정리
# ============================================================

def normalize_text(value):

    if value is None:
        return ""

    return str(value).strip().lower()


# ============================================================
# 5. 기업 이름으로 Neo4j Company 찾기
# ============================================================

def find_company(tx, company_name):

    query = """
    MATCH (c:Entity)
    WHERE c.Type = 'Company'
      AND (
          toLower(c.name) = toLower($company_name)
          OR toLower(c.name) CONTAINS toLower($company_name)
          OR toLower($company_name) CONTAINS toLower(c.name)
      )
    RETURN
        c.entity_id AS entity_id,
        c.name AS name,
        c.Type AS type,
        c.description AS description
    LIMIT 10
    """

    result = tx.run(
        query,
        company_name=company_name
    )

    return [record.data() for record in result]


# ============================================================
# 6. Company → Tier 1 Supplier 찾기
# ============================================================

def find_tier1_suppliers(tx, company_name):

    query = """
    MATCH (s:Entity)-[r:KG_RELATION]->(c:Entity)
    WHERE c.Type = 'Company'
      AND s.Type = 'Supplier'
      AND r.type = 'Supplies'
      AND r.tier = '1'
      AND (
          toLower(c.name) = toLower($company_name)
          OR toLower(c.name) CONTAINS toLower($company_name)
          OR toLower($company_name) CONTAINS toLower(c.name)
      )

    RETURN
        s.entity_id AS supplier_id,
        s.name AS supplier_name,
        s.Type AS supplier_type,

        c.entity_id AS company_id,
        c.name AS company_name,

        r.tier AS tier,
        r.type AS relation_type,
        r.confidence AS confidence,
        r.evidence AS evidence,
        r.notes AS notes,
        r.relation_id AS relation_id
    """

    result = tx.run(
        query,
        company_name=company_name
    )

    return [record.data() for record in result]


# ============================================================
# 7. Tier 1 → Tier 2 Supplier 찾기
# ============================================================

def find_tier2_suppliers(tx, tier1_name):

    query = """
    MATCH (s2:Entity)-[r:KG_RELATION]->(s1:Entity)
    WHERE s2.Type = 'Supplier'
      AND s1.Type = 'Supplier'
      AND r.type = 'Supplies'
      AND r.tier = '2'
      AND (
          toLower(s1.name) = toLower($tier1_name)
          OR toLower(s1.name) CONTAINS toLower($tier1_name)
          OR toLower($tier1_name) CONTAINS toLower(s1.name)
      )

    RETURN
        s2.entity_id AS supplier_id,
        s2.name AS supplier_name,
        s2.Type AS supplier_type,

        s1.entity_id AS tier1_id,
        s1.name AS tier1_name,

        r.tier AS tier,
        r.type AS relation_type,
        r.confidence AS confidence,
        r.evidence AS evidence,
        r.notes AS notes,
        r.relation_id AS relation_id
    """

    result = tx.run(
        query,
        tier1_name=tier1_name
    )

    return [record.data() for record in result]


# ============================================================
# 8. 공급망 경로 생성
# ============================================================

def build_supply_chain_path(company, tier1, tier2):

    return {
        "company": company,
        "tier1_supplier": tier1.get("supplier_name"),
        "tier2_supplier": tier2.get("supplier_name"),
        "path": [
            tier2.get("supplier_name"),
            tier1.get("supplier_name"),
            company
        ],
        "tiers": {
            "tier2": tier2.get("supplier_name"),
            "tier1": tier1.get("supplier_name"),
            "company": company
        }
    }


# ============================================================
# 9. Agent 1 한 건 처리
# ============================================================

def process_article(article):

    companies = article.get("companies_involved", [])

    if not companies:
        return {
            "status": "no_company",
            "companies": [],
            "tier1_suppliers": [],
            "tier2_suppliers": [],
            "supply_chain_paths": []
        }

    article_result = {
        "status": "processed",
        "companies": companies,
        "countries": article.get("countries_involved", []),
        "industries": article.get("industries_involved", []),
        "disruption_type": article.get("disruption_type"),
        "event": article.get("event"),
        "risk_exposure_questions": article.get(
            "risk_exposure_questions", []
        ),

        "matched_companies": [],
        "tier1_suppliers": [],
        "tier2_suppliers": [],
        "supply_chain_paths": []
    }

    with driver.session() as session:

        # ----------------------------------------------------
        # Company 검색
        # ----------------------------------------------------

        for company_name in companies:

            company_matches = session.execute_read(
                find_company,
                company_name
            )

            article_result["matched_companies"].extend(
                company_matches
            )

            # ------------------------------------------------
            # Tier 1 검색
            # ------------------------------------------------

            tier1_results = session.execute_read(
                find_tier1_suppliers,
                company_name
            )

            article_result["tier1_suppliers"].extend(
                tier1_results
            )

            # ------------------------------------------------
            # Tier 2 검색
            # ------------------------------------------------

            for tier1 in tier1_results:

                tier1_name = tier1.get("supplier_name")

                if not tier1_name:
                    continue

                tier2_results = session.execute_read(
                    find_tier2_suppliers,
                    tier1_name
                )

                article_result["tier2_suppliers"].extend(
                    tier2_results
                )

                # --------------------------------------------
                # Tier 2 → Tier 1 → Company 경로
                # --------------------------------------------

                for tier2 in tier2_results:

                    path = build_supply_chain_path(
                        company_name,
                        tier1,
                        tier2
                    )

                    article_result["supply_chain_paths"].append(
                        path
                    )

    # --------------------------------------------------------
    # 중복 제거
    # --------------------------------------------------------

    article_result["matched_companies"] = remove_duplicates(
        article_result["matched_companies"],
        key_fields=["entity_id", "name"]
    )

    article_result["tier1_suppliers"] = remove_duplicates(
        article_result["tier1_suppliers"],
        key_fields=["supplier_id", "supplier_name"]
    )

    article_result["tier2_suppliers"] = remove_duplicates(
        article_result["tier2_suppliers"],
        key_fields=["supplier_id", "supplier_name", "tier1_id"]
    )

    article_result["supply_chain_paths"] = remove_duplicates(
        article_result["supply_chain_paths"],
        key_fields=[
            "company",
            "tier1_supplier",
            "tier2_supplier"
        ]
    )

    return article_result


# ============================================================
# 10. 중복 제거
# ============================================================

def remove_duplicates(items, key_fields):

    unique = []
    seen = set()

    for item in items:

        key = tuple(
            item.get(field)
            for field in key_fields
        )

        if key not in seen:
            seen.add(key)
            unique.append(item)

    return unique


# ============================================================
# 11. 결과 저장
# ============================================================

def save_results(results):

    output = {
        "updated_at": datetime.utcnow().isoformat(),
        "source": "agent1_results.json",
        "agent": "Agent 2 - Knowledge Graph Builder",
        "total_articles": len(results),
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

    print(f"\nAgent 2 결과 저장 완료:")
    print(OUTPUT_FILE)


# ============================================================
# 12. 메인
# ============================================================

def main():

    print("=" * 60)
    print("Agent 2 - Knowledge Graph Builder")
    print("=" * 60)

    # Agent 1 결과 읽기
    agent1_results = load_agent1_results()

    print(
        f"Agent 1 결과: {len(agent1_results)}건"
    )

    if not agent1_results:
        print("처리할 Agent 1 결과가 없습니다.")
        return

    results = []

    for index, article in enumerate(agent1_results, start=1):

        print(
            f"\n[{index}/{len(agent1_results)}] 처리 중..."
        )

        title = article.get(
            "title",
            article.get("event", "Unknown")
        )

        print(f"Event: {title}")

        result = process_article(article)

        print(
            f"  Company: "
            f"{len(result['matched_companies'])}"
        )

        print(
            f"  Tier 1: "
            f"{len(result['tier1_suppliers'])}"
        )

        print(
            f"  Tier 2: "
            f"{len(result['tier2_suppliers'])}"
        )

        print(
            f"  Paths: "
            f"{len(result['supply_chain_paths'])}"
        )

        results.append({
            "article": article,
            "kg_analysis": result
        })

    save_results(results)

    print("\n" + "=" * 60)
    print("Agent 2 완료")
    print("=" * 60)


# ============================================================
# 13. 종료 처리
# ============================================================

if __name__ == "__main__":

    try:
        main()

    finally:
        driver.close()
```

