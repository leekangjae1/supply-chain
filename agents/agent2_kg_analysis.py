import os
import json
import hashlib
from pathlib import Path
from datetime import datetime, timezone

from neo4j import GraphDatabase


# ============================================================
# 1. 경로 설정
# ============================================================

BASE_DIR = Path(__file__).resolve().parent.parent

INPUT_FILE = BASE_DIR / "agent1_results.json"
OUTPUT_FILE = BASE_DIR / "agent2_results.json"


# ============================================================
# 2. 환경변수
#    GitHub Actions에서는 GitHub Secrets가 환경변수로 들어옴
# ============================================================

NEO4J_URI = os.getenv("NEO4J_URI")
NEO4J_USERNAME = os.getenv("NEO4J_USERNAME")
NEO4J_PASSWORD = os.getenv("NEO4J_PASSWORD")


# ============================================================
# 3. 환경변수 확인
# ============================================================

required_env = {
    "NEO4J_URI": NEO4J_URI,
    "NEO4J_USERNAME": NEO4J_USERNAME,
    "NEO4J_PASSWORD": NEO4J_PASSWORD,
}

missing_env = [key for key, value in required_env.items() if not value]

if missing_env:
    raise RuntimeError(
        "다음 환경변수가 설정되지 않았습니다: "
        + ", ".join(missing_env)
    )


# ============================================================
# 4. Agent 1 결과 불러오기
# ============================================================

if not INPUT_FILE.exists():
    raise FileNotFoundError(
        f"Agent 1 결과 파일을 찾을 수 없습니다: {INPUT_FILE}"
    )

with open(INPUT_FILE, "r", encoding="utf-8") as f:
    agent1_data = json.load(f)


# ============================================================
# 5. JSON 형식 정리
# ============================================================

if isinstance(agent1_data, dict):
    # Agent 1 결과가 {"articles": [...]} 형태인 경우
    if "articles" in agent1_data:
        articles = agent1_data["articles"]
    else:
        # 단일 기사 결과인 경우
        articles = [agent1_data]

elif isinstance(agent1_data, list):
    articles = agent1_data

else:
    raise ValueError("agent1_results.json의 형식을 확인해주세요.")


# ============================================================
# 6. Neo4j 연결
# ============================================================

driver = GraphDatabase.driver(
    NEO4J_URI,
    auth=(NEO4J_USERNAME, NEO4J_PASSWORD)
)


# ============================================================
# 7. Event ID 생성
# ============================================================

def create_event_id(article):
    """
    같은 뉴스가 다시 들어와도
    같은 Event ID를 사용하도록 URL 기반 ID 생성
    """

    url = article.get("url", "")

    if not url:
        base = (
            article.get("event", "")
            + article.get("title", "")
            + article.get("summary", "")
        )
    else:
        base = url

    hash_value = hashlib.sha256(
        base.encode("utf-8")
    ).hexdigest()[:16]

    return f"EVENT_{hash_value}"


# ============================================================
# 8. 리스트 안전하게 처리
# ============================================================

def safe_list(value):
    if value is None:
        return []

    if isinstance(value, list):
        return value

    return [value]


# ============================================================
# 9. Company 검색
# ============================================================

def find_company(tx, company_name):
    """
    기존 Neo4j KG에서 Company 노드를 찾는다.
    """

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
        c.Type AS type
    LIMIT 5
    """

    result = tx.run(
        query,
        company_name=company_name
    )

    return [record.data() for record in result]


# ============================================================
# 10. Event 생성
# ============================================================

def create_event(tx, article, event_id):
    """
    Agent 1의 뉴스 분석 결과를 Neo4j Event 노드로 생성/업데이트
    """

    disruption_type = article.get(
        "disruption_type",
        "Other"
    )

    event_name = article.get(
        "event",
        "Unknown Event"
    )

    summary = article.get(
        "summary",
        ""
    )

    reason = article.get(
        "reason",
        ""
    )

    risk_questions = safe_list(
        article.get("risk_exposure_questions")
    )

    countries = safe_list(
        article.get("countries_involved")
    )

    industries = safe_list(
        article.get("industries_involved")
    )

    companies = safe_list(
        article.get("companies_involved")
    )

    title = article.get(
        "title",
        ""
    )

    url = article.get(
        "url",
        ""
    )

    created_at = datetime.now(
        timezone.utc
    ).isoformat()

    query = """
    MERGE (e:Entity {
        entity_id: $event_id
    })

    SET
        e.Type = 'Event',
        e.name = $event_name,
        e.disruption_type = $disruption_type,
        e.title = $title,
        e.url = $url,
        e.summary = $summary,
        e.reason = $reason,
        e.risk_exposure_questions = $risk_questions,
        e.countries_involved = $countries,
        e.industries_involved = $industries,
        e.companies_involved = $companies,
        e.updated_at = $created_at

    RETURN
        e.entity_id AS entity_id,
        e.name AS name
    """

    result = tx.run(
        query,
        event_id=event_id,
        event_name=event_name,
        disruption_type=disruption_type,
        title=title,
        url=url,
        summary=summary,
        reason=reason,
        risk_questions=risk_questions,
        countries=countries,
        industries=industries,
        companies=companies,
        created_at=created_at
    )

    return result.single().data()


# ============================================================
# 11. Event → Company 관계 생성
# ============================================================

def connect_event_company(
    tx,
    event_id,
    company_entity_id
):
    """
    Event가 영향을 받는 Company와 연결된다.

    Event -[KG_RELATION {type: 'Affected_By'}]-> Company
    """

    query = """
    MATCH (e:Entity {entity_id: $event_id})
    MATCH (c:Entity {entity_id: $company_entity_id})

    MERGE (e)-[r:KG_RELATION {
        relation_id: $relation_id
    }]->(c)

    SET
        r.type = 'Affected_By',
        r.source_type = 'Event',
        r.target_type = 'Company',
        r.source_name = e.name,
        r.target_name = c.name,
        r.confidence = 'Agent1',
        r.source = 'Agent1 News Analysis'

    RETURN
        e.name AS event,
        c.name AS company
    """

    relation_id = (
        f"{event_id}_Affected_By_{company_entity_id}"
    )

    result = tx.run(
        query,
        event_id=event_id,
        company_entity_id=company_entity_id,
        relation_id=relation_id
    )

    record = result.single()

    if record:
        return record.data()

    return None


# ============================================================
# 12. Company의 Tier 1 공급업체 찾기
# ============================================================

def find_tier1_suppliers(
    tx,
    company_entity_id
):

    query = """
    MATCH (s:Entity)-[r:KG_RELATION]->(c:Entity)

    WHERE s.Type = 'Supplier'
      AND c.Type = 'Company'
      AND c.entity_id = $company_entity_id
      AND r.type = 'Supplies'
      AND r.tier = '1'

    RETURN
        s.entity_id AS entity_id,
        s.name AS name
    """

    result = tx.run(
        query,
        company_entity_id=company_entity_id
    )

    return [record.data() for record in result]


# ============================================================
# 13. Tier 1 → Tier 2 공급업체 찾기
# ============================================================

def find_tier2_suppliers(
    tx,
    tier1_entity_id
):

    query = """
    MATCH (s2:Entity)-[r:KG_RELATION]->(s1:Entity)

    WHERE s2.Type = 'Supplier'
      AND s1.Type = 'Supplier'
      AND s1.entity_id = $tier1_entity_id
      AND r.type = 'Supplies'
      AND r.tier = '2'

    RETURN
        s2.entity_id AS entity_id,
        s2.name AS name
    """

    result = tx.run(
        query,
        tier1_entity_id=tier1_entity_id
    )

    return [record.data() for record in result]


# ============================================================
# 14. Event와 공급망 Path 연결
# ============================================================

def connect_event_to_supplier_path(
    tx,
    event_id,
    tier2_id,
    tier1_id,
    company_id
):
    """
    기존 KG의 공급망 관계를 이용하여

    Event
      ↓
    Tier 2 Supplier
      ↓
    Tier 1 Supplier
      ↓
    Company

    구조를 만든다.

    기존 Supplies 관계는 수정하지 않는다.
    """

    query = """
    MATCH (e:Entity {entity_id: $event_id})
    MATCH (s2:Entity {entity_id: $tier2_id})
    MATCH (s1:Entity {entity_id: $tier1_id})
    MATCH (c:Entity {entity_id: $company_id})

    MERGE (e)-[r:KG_RELATION {
        relation_id: $relation_id
    }]->(s2)

    SET
        r.type = 'Risk_Exposure',
        r.source_type = 'Event',
        r.target_type = 'Supplier',
        r.tier = '2',
        r.source_name = e.name,
        r.target_name = s2.name,
        r.notes = 'Agent 1 news event linked to existing Tier 2 supply chain path'

    RETURN
        e.name AS event,
        s2.name AS tier2_supplier,
        s1.name AS tier1_supplier,
        c.name AS company
    """

    relation_id = (
        f"{event_id}_Risk_Exposure_{tier2_id}"
    )

    result = tx.run(
        query,
        event_id=event_id,
        tier2_id=tier2_id,
        tier1_id=tier1_id,
        company_id=company_id,
        relation_id=relation_id
    )

    record = result.single()

    if record:
        return record.data()

    return None


# ============================================================
# 15. Agent 2 실행
# ============================================================

agent2_results = []


with driver.session() as session:

    for article in articles:

        # ----------------------------------------------------
        # 공급망 교란 뉴스인지 확인
        # ----------------------------------------------------

        if not article.get(
            "is_supply_chain_disruption",
            False
        ):
            continue

        event_id = create_event_id(article)

        print("\n" + "=" * 70)
        print("Agent 2 처리 시작")
        print("=" * 70)

        print(
            f"Event: {article.get('event', 'Unknown')}"
        )

        # ----------------------------------------------------
        # 1. Event 생성
        # ----------------------------------------------------

        event_result = session.execute_write(
            create_event,
            article,
            event_id
        )

        print(
            f"✓ Event 생성/업데이트: "
            f"{event_result['name']}"
        )

        # ----------------------------------------------------
        # 2. Agent 1에서 회사 목록 가져오기
        # ----------------------------------------------------

        companies = safe_list(
            article.get(
                "companies_involved"
            )
        )

        article_result = {
            "event_id": event_id,
            "event": article.get(
                "event",
                ""
            ),
            "disruption_type": article.get(
                "disruption_type",
                ""
            ),
            "companies": [],
            "supply_chain_paths": []
        }

        # ----------------------------------------------------
        # 3. Company 검색
        # ----------------------------------------------------

        for company_name in companies:

            matched_companies = session.execute_read(
                find_company,
                company_name
            )

            if not matched_companies:
                print(
                    f"⚠ Company 매칭 실패: "
                    f"{company_name}"
                )

                article_result["companies"].append({
                    "name": company_name,
                    "matched": False,
                    "tier1_suppliers": []
                })

                continue

            # 첫 번째 매칭 Company 사용
            company = matched_companies[0]

            company_id = company["entity_id"]
            company_real_name = company["name"]

            print(
                f"✓ Company 매칭: "
                f"{company_real_name}"
            )

            # ------------------------------------------------
            # 4. Event → Company 관계 생성
            # ------------------------------------------------

            session.execute_write(
                connect_event_company,
                event_id,
                company_id
            )

            # ------------------------------------------------
            # 5. Tier 1 Supplier 검색
            # ------------------------------------------------

            tier1_suppliers = session.execute_read(
                find_tier1_suppliers,
                company_id
            )

            print(
                f"  Tier 1 Supplier: "
                f"{len(tier1_suppliers)}개"
            )

            company_result = {
                "name": company_real_name,
                "entity_id": company_id,
                "matched": True,
                "tier1_suppliers": []
            }

            # ------------------------------------------------
            # 6. Tier 1 → Tier 2 검색
            # ------------------------------------------------

            for tier1 in tier1_suppliers:

                tier1_id = tier1["entity_id"]
                tier1_name = tier1["name"]

                tier2_suppliers = session.execute_read(
                    find_tier2_suppliers,
                    tier1_id
                )

                tier1_result = {
                    "name": tier1_name,
                    "entity_id": tier1_id,
                    "tier2_suppliers": []
                }

                # --------------------------------------------
                # 7. Tier 2 Path 저장
                # --------------------------------------------

                for tier2 in tier2_suppliers:

                    tier2_id = tier2["entity_id"]
                    tier2_name = tier2["name"]

                    # Event → Tier2 연결
                    path_result = session.execute_write(
                        connect_event_to_supplier_path,
                        event_id,
                        tier2_id,
                        tier1_id,
                        company_id
                    )

                    path = {
                        "tier2_supplier": tier2_name,
                        "tier1_supplier": tier1_name,
                        "company": company_real_name
                    }

                    tier1_result[
                        "tier2_suppliers"
                    ].append(path)

                    article_result[
                        "supply_chain_paths"
                    ].append(path)

                    print(
                        f"  Path: "
                        f"{tier2_name} "
                        f"→ {tier1_name} "
                        f"→ {company_real_name}"
                    )

                company_result[
                    "tier1_suppliers"
                ].append(tier1_result)

            article_result[
                "companies"
            ].append(company_result)

        agent2_results.append(
            article_result
        )


# ============================================================
# 16. Neo4j 연결 종료
# ============================================================

driver.close()


# ============================================================
# 17. Agent 2 결과 저장
# ============================================================

output_data = {
    "generated_at": datetime.now(
        timezone.utc
    ).isoformat(),

    "agent": "Agent 2",

    "description": (
        "Agent 1 news analysis results are used "
        "to create/update Event nodes and connect "
        "them to the existing supply chain knowledge graph."
    ),

    "results": agent2_results
}


with open(
    OUTPUT_FILE,
    "w",
    encoding="utf-8"
) as f:

    json.dump(
        output_data,
        f,
        ensure_ascii=False,
        indent=2
    )


# ============================================================
# 18. 완료
# ============================================================

print("\n" + "=" * 70)
print("Agent 2 완료")
print("=" * 70)

print(
    f"처리된 Event: "
    f"{len(agent2_results)}개"
)

print(
    f"결과 파일: "
    f"{OUTPUT_FILE}"
)

print(
    "\nNeo4j KG에 다음 구조가 생성/연결되었습니다:"
)

print(
    "Event → Company"
)

print(
    "Event → Tier2 Supplier → Tier1 Supplier → Company"
)

print(
    "\n기존 Tier 1 / Tier 2 Supplies 관계는 수정하지 않았습니다."
)
