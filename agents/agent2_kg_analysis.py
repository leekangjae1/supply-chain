# ============================================================
# Agent 2 - Knowledge Graph Analysis
# ============================================================
# Input:
#   agent1_results.json
#
# Output:
#   agent2_results.json
#
# 역할:
#   Agent 1에서 탐지한 공급망 교란 이벤트를
#   기존 Neo4j Supply Chain KG와 연결한다.
#
# 구조:
#
#   Event
#      ↓
#   Company
#      ↓
#   Tier-1 Supplier
#      ↓
#   Tier-2 Supplier
#
# 기존 Supplies 관계는 수정하지 않는다.
# ============================================================

import os
import json
import hashlib
import re
from pathlib import Path
from datetime import datetime, timezone
from difflib import SequenceMatcher

from neo4j import GraphDatabase


# ============================================================
# 1. 경로 설정
# ============================================================

BASE_DIR = Path(__file__).resolve().parent.parent

INPUT_FILE = BASE_DIR / "agent1_results.json"
OUTPUT_FILE = BASE_DIR / "agent2_results.json"


# ============================================================
# 2. 환경변수
# ============================================================

NEO4J_URI = os.getenv("NEO4J_URI")
NEO4J_USERNAME = os.getenv("NEO4J_USERNAME")
NEO4J_PASSWORD = os.getenv("NEO4J_PASSWORD")


required_env = {
    "NEO4J_URI": NEO4J_URI,
    "NEO4J_USERNAME": NEO4J_USERNAME,
    "NEO4J_PASSWORD": NEO4J_PASSWORD,
}

missing_env = [
    key
    for key, value in required_env.items()
    if not value
]

if missing_env:
    raise RuntimeError(
        "다음 환경변수가 설정되지 않았습니다: "
        + ", ".join(missing_env)
    )


# ============================================================
# 3. Agent 1 결과 불러오기
# ============================================================

if not INPUT_FILE.exists():
    raise FileNotFoundError(
        f"Agent 1 결과 파일을 찾을 수 없습니다: {INPUT_FILE}"
    )


with open(INPUT_FILE, "r", encoding="utf-8") as f:
    agent1_data = json.load(f)


# ============================================================
# 4. JSON 형식 정리
# ============================================================

if isinstance(agent1_data, dict):

    if "results" in agent1_data:
        articles = agent1_data["results"]

    elif "articles" in agent1_data:
        articles = agent1_data["articles"]

    else:
        articles = [agent1_data]

elif isinstance(agent1_data, list):

    articles = agent1_data

else:

    raise ValueError(
        "agent1_results.json의 형식을 확인해주세요."
    )


print("=" * 70)
print("Agent 2 시작")
print("=" * 70)
print(f"Agent 1 입력 기사 수: {len(articles)}")


# ============================================================
# 5. Neo4j 연결
# ============================================================

driver = GraphDatabase.driver(
    NEO4J_URI,
    auth=(
        NEO4J_USERNAME,
        NEO4J_PASSWORD
    )
)


# ============================================================
# 6. Event ID 생성
# ============================================================

def create_event_id(article):

    url = article.get("url", "")

    if not url:

        base = (
            str(article.get("event", ""))
            + str(article.get("title", ""))
            + str(article.get("summary", ""))
        )

    else:

        base = url

    hash_value = hashlib.sha256(
        base.encode("utf-8")
    ).hexdigest()[:16]

    return f"EVENT_{hash_value}"


# ============================================================
# 7. 리스트 안전 처리
# ============================================================

def safe_list(value):

    if value is None:
        return []

    if isinstance(value, list):
        return value

    return [value]


# ============================================================
# 8. 회사명 정규화
# ============================================================

def normalize_company_name(name):

    if name is None:
        return ""

    name = str(name).strip().lower()

    # 특수문자 제거
    name = re.sub(r"[^a-z0-9가-힣]", "", name)

    # 회사 형태를 나타내는 일반적인 표현 제거
    removable_words = [
        "corporation",
        "company",
        "co",
        "limited",
        "ltd",
        "incorporated",
        "inc",
        "corp",
        "group",
        "holdings",
        "electronics",
        "motor",
    ]

    for word in removable_words:
        name = name.replace(word, "")

    return name


# ============================================================
# 9. 회사 Alias
# ============================================================
#
# Agent 1이 사용하는 이름과
# Neo4j KG에 저장된 이름이 다를 경우 사용
#
# 예:
#   Hyundai Motor Company → Hyundai
#   Kia Corporation       → Kia
#   SK Hynix              → SK hynix
#
# ============================================================

COMPANY_ALIASES = {

    "hyundaimotorcompany": [
        "hyundai",
        "hyundai motor",
        "hyundai motor company",
    ],

    "hyundai": [
        "hyundai",
        "hyundai motor",
        "hyundai motor company",
    ],

    "kiacorporation": [
        "kia",
        "kia corporation",
        "kia motors",
    ],

    "kia": [
        "kia",
        "kia corporation",
        "kia motors",
    ],

    "samsungelectronics": [
        "samsung electronics",
        "samsung",
    ],

    "samsung": [
        "samsung",
        "samsung electronics",
    ],

    "skhynix": [
        "sk hynix",
        "skhynix",
        "hynix",
    ],

    "skhynixinc": [
        "sk hynix",
        "skhynix",
        "hynix",
    ],

    "toyotamotorcorporation": [
        "toyota",
        "toyota motor",
        "toyota motor corporation",
    ],

    "toyota": [
        "toyota",
        "toyota motor",
        "toyota motor corporation",
    ],

    "honda": [
        "honda",
        "honda motor",
        "honda motor co",
    ],

    "hondamotor": [
        "honda",
        "honda motor",
    ],

    "posco": [
        "posco",
    ],

    "hyundaasteel": [
        "hyundai steel",
        "hyundai steel company",
    ],

    "lg": [
        "lg",
        "lg electronics",
    ],

    "lgelectronics": [
        "lg electronics",
        "lg",
    ],

    "adidas": [
        "adidas",
        "adidas ag",
    ],

    "nike": [
        "nike",
        "nike inc",
    ],

    "patagonia": [
        "patagonia",
        "patagonia inc",
    ],

    "nestle": [
        "nestle",
        "nestlé",
    ],
}


# ============================================================
# 10. Agent 1 회사명에서 실제 검색 후보 만들기
# ============================================================

def get_company_aliases(company_name):

    normalized = normalize_company_name(
        company_name
    )

    aliases = [
        str(company_name)
    ]

    # 직접 alias dictionary 검색
    if normalized in COMPANY_ALIASES:

        aliases.extend(
            COMPANY_ALIASES[normalized]
        )

    # normalized alias key와 비교
    for key, values in COMPANY_ALIASES.items():

        if normalize_company_name(key) == normalized:

            aliases.extend(values)

    # 중복 제거
    result = []

    for alias in aliases:

        if alias and alias not in result:
            result.append(alias)

    return result


# ============================================================
# 11. Neo4j의 모든 Company 노드 조회
# ============================================================

def get_all_companies(tx):

    query = """
    MATCH (c:Entity)

    WHERE
        toLower(toString(coalesce(c.Type, '')))
        = 'company'
        OR
        toLower(toString(coalesce(c.type, '')))
        = 'company'

    RETURN
        c.entity_id AS entity_id,
        c.name AS name,
        coalesce(c.Type, c.type) AS type
    """

    result = tx.run(query)

    return [
        record.data()
        for record in result
    ]


# ============================================================
# 12. 회사명 유사도
# ============================================================

def similarity_score(name1, name2):

    n1 = normalize_company_name(name1)
    n2 = normalize_company_name(name2)

    if not n1 or not n2:
        return 0.0

    # 완전 일치
    if n1 == n2:
        return 1.0

    # 포함 관계
    if n1 in n2 or n2 in n1:

        shorter = min(
            len(n1),
            len(n2)
        )

        longer = max(
            len(n1),
            len(n2)
        )

        if longer == 0:
            return 0.0

        return 0.90 * (
            shorter / longer
        )

    # 일반적인 문자열 유사도
    return SequenceMatcher(
        None,
        n1,
        n2
    ).ratio()


# ============================================================
# 13. Company 검색
# ============================================================

def find_company(
    tx,
    company_name
):

    all_companies = get_all_companies(tx)

    if not all_companies:
        return []

    aliases = get_company_aliases(
        company_name
    )

    candidates = []

    for company in all_companies:

        kg_name = company.get(
            "name",
            ""
        )

        if not kg_name:
            continue

        best_score = 0.0
        best_alias = ""

        for alias in aliases:

            score = similarity_score(
                alias,
                kg_name
            )

            if score > best_score:

                best_score = score
                best_alias = alias

        candidates.append(
            {
                "entity_id": company.get(
                    "entity_id"
                ),
                "name": kg_name,
                "type": company.get(
                    "type"
                ),
                "score": round(
                    best_score,
                    4
                ),
                "matched_alias": best_alias,
            }
        )

    # 점수 높은 순
    candidates.sort(
        key=lambda x: x["score"],
        reverse=True
    )

    # --------------------------------------------------------
    # 매칭 기준
    # --------------------------------------------------------
    #
    # 1. 완전/거의 일치
    # 2. Alias 일치
    # 3. 포함 관계
    #
    # 최소 0.65 이상만 실제 매칭
    #
    # --------------------------------------------------------

    matched = [
        x
        for x in candidates
        if x["score"] >= 0.65
    ]

    return matched[:5]


# ============================================================
# 14. Event 생성
# ============================================================

def create_event(
    tx,
    article,
    event_id
):

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
        article.get(
            "risk_exposure_questions"
        )
    )

    countries = safe_list(
        article.get(
            "countries_involved"
        )
    )

    industries = safe_list(
        article.get(
            "industries_involved"
        )
    )

    companies = safe_list(
        article.get(
            "companies_involved"
        )
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

    record = result.single()

    if record:
        return record.data()

    return None


# ============================================================
# 15. Event → Company
# ============================================================

def connect_event_company(
    tx,
    event_id,
    company_entity_id
):

    query = """
    MATCH (e:Entity {
        entity_id: $event_id
    })

    MATCH (c:Entity {
        entity_id: $company_entity_id
    })

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
        f"{event_id}"
        f"_Affected_By_"
        f"{company_entity_id}"
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
# 16. Tier-1 Supplier 검색
# ============================================================

def find_tier1_suppliers(
    tx,
    company_entity_id
):

    query = """
    MATCH (s:Entity)-[r:KG_RELATION]->(c:Entity)

    WHERE
        toLower(toString(coalesce(s.Type, '')))
            = 'supplier'

        AND
        (
            toLower(toString(coalesce(c.Type, '')))
                = 'company'
            OR
            toLower(toString(coalesce(c.type, '')))
                = 'company'
        )

        AND c.entity_id = $company_entity_id

        AND toLower(
            toString(
                coalesce(r.type, '')
            )
        ) = 'supplies'

        AND toLower(
            replace(
                replace(
                    replace(
                        toString(
                            coalesce(r.tier, '')
                        ),
                        ' ',
                        ''
                    ),
                    '-',
                    ''
                ),
                '_',
                ''
            )
        ) IN [
            '1',
            'tier1'
        ]

    RETURN DISTINCT
        s.entity_id AS entity_id,
        s.name AS name
    """

    result = tx.run(
        query,
        company_entity_id=company_entity_id
    )

    return [
        record.data()
        for record in result
    ]


# ============================================================
# 17. Tier-2 Supplier 검색
# ============================================================

def find_tier2_suppliers(
    tx,
    tier1_entity_id
):

    query = """
    MATCH (s2:Entity)-[r:KG_RELATION]->(s1:Entity)

    WHERE
        toLower(toString(coalesce(s2.Type, '')))
            = 'supplier'

        AND
        toLower(toString(coalesce(s1.Type, '')))
            = 'supplier'

        AND s1.entity_id = $tier1_entity_id

        AND toLower(
            toString(
                coalesce(r.type, '')
            )
        ) = 'supplies'

        AND toLower(
            replace(
                replace(
                    replace(
                        toString(
                            coalesce(r.tier, '')
                        ),
                        ' ',
                        ''
                    ),
                    '-',
                    ''
                ),
                '_',
                ''
            )
        ) IN [
            '2',
            'tier2'
        ]

    RETURN DISTINCT
        s2.entity_id AS entity_id,
        s2.name AS name
    """

    result = tx.run(
        query,
        tier1_entity_id=tier1_entity_id
    )

    return [
        record.data()
        for record in result
    ]


# ============================================================
# 18. Event → Tier-2 Risk Exposure
# ============================================================

def connect_event_to_supplier_path(
    tx,
    event_id,
    tier2_id,
    tier1_id,
    company_id
):

    query = """
    MATCH (e:Entity {
        entity_id: $event_id
    })

    MATCH (s2:Entity {
        entity_id: $tier2_id
    })

    MATCH (s1:Entity {
        entity_id: $tier1_id
    })

    MATCH (c:Entity {
        entity_id: $company_id
    })

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
        r.notes =
            'Agent 1 news event linked to '
            + 'existing Tier 2 supply chain path'

    RETURN
        e.name AS event,
        s2.name AS tier2_supplier,
        s1.name AS tier1_supplier,
        c.name AS company
    """

    relation_id = (
        f"{event_id}"
        f"_Risk_Exposure_"
        f"{tier2_id}"
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
# 19. Agent 2 실행
# ============================================================

agent2_results = []

total_matched_companies = 0
total_tier1_suppliers = 0
total_tier2_suppliers = 0
total_paths = 0


with driver.session() as session:

    for article in articles:

        # ----------------------------------------------------
        # 공급망 교란 뉴스만 처리
        # ----------------------------------------------------

        if not article.get(
            "is_supply_chain_disruption",
            False
        ):
            continue

        event_id = create_event_id(
            article
        )

        print("\n" + "=" * 70)
        print("Agent 2 처리 시작")
        print("=" * 70)

        print(
            f"Event: "
            f"{article.get('event', 'Unknown')}"
        )

        # ----------------------------------------------------
        # Event 생성
        # ----------------------------------------------------

        event_result = session.execute_write(
            create_event,
            article,
            event_id
        )

        if event_result:

            print(
                f"✓ Event 생성/업데이트: "
                f"{event_result['name']}"
            )

        # ----------------------------------------------------
        # Agent 1 회사 목록
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
        # Company 검색
        # ----------------------------------------------------

        for company_item in companies:

            # -----------------------------------------------
            # 회사명이 문자열이 아닐 경우 처리
            # -----------------------------------------------

            if isinstance(
                company_item,
                dict
            ):

                company_name = (
                    company_item.get(
                        "name"
                    )
                    or
                    company_item.get(
                        "company"
                    )
                    or
                    company_item.get(
                        "company_name"
                    )
                )

            else:

                company_name = str(
                    company_item
                )

            if not company_name:

                continue

            print(
                f"\n[Company 검색] "
                f"{company_name}"
            )

            aliases = get_company_aliases(
                company_name
            )

            print(
                f"  검색 후보: "
                f"{aliases}"
            )

            matched_companies = session.execute_read(
                find_company,
                company_name
            )

            # ------------------------------------------------
            # Company 매칭 실패
            # ------------------------------------------------

            if not matched_companies:

                print(
                    f"❌ Company 매칭 실패: "
                    f"{company_name}"
                )

                article_result[
                    "companies"
                ].append(
                    {
                        "name": company_name,
                        "matched": False,
                        "tier1_suppliers": []
                    }
                )

                continue

            # ------------------------------------------------
            # 가장 높은 점수의 Company 사용
            # ------------------------------------------------

            company = matched_companies[0]

            company_id = company[
                "entity_id"
            ]

            company_real_name = company[
                "name"
            ]

            match_score = company.get(
                "score",
                0.0
            )

            matched_alias = company.get(
                "matched_alias",
                ""
            )

            print(
                f"✓ Company 매칭 성공"
            )

            print(
                f"  Agent 1 이름: "
                f"{company_name}"
            )

            print(
                f"  KG 이름: "
                f"{company_real_name}"
            )

            print(
                f"  매칭 Alias: "
                f"{matched_alias}"
            )

            print(
                f"  매칭 점수: "
                f"{match_score}"
            )

            total_matched_companies += 1

            # ------------------------------------------------
            # Event → Company
            # ------------------------------------------------

            session.execute_write(
                connect_event_company,
                event_id,
                company_id
            )

            # ------------------------------------------------
            # Tier-1 검색
            # ------------------------------------------------

            tier1_suppliers = session.execute_read(
                find_tier1_suppliers,
                company_id
            )

            print(
                f"  Tier-1 Supplier: "
                f"{len(tier1_suppliers)}개"
            )

            total_tier1_suppliers += len(
                tier1_suppliers
            )

            company_result = {

                "name": company_real_name,

                "entity_id": company_id,

                "matched": True,

                "matched_from": company_name,

                "match_score": match_score,

                "tier1_suppliers": []
            }

            # ------------------------------------------------
            # Tier-1 → Tier-2
            # ------------------------------------------------

            for tier1 in tier1_suppliers:

                tier1_id = tier1[
                    "entity_id"
                ]

                tier1_name = tier1[
                    "name"
                ]

                tier2_suppliers = session.execute_read(
                    find_tier2_suppliers,
                    tier1_id
                )

                print(
                    f"    Tier-1: "
                    f"{tier1_name}"
                )

                print(
                    f"      Tier-2: "
                    f"{len(tier2_suppliers)}개"
                )

                total_tier2_suppliers += len(
                    tier2_suppliers
                )

                tier1_result = {

                    "name": tier1_name,

                    "entity_id": tier1_id,

                    "tier2_suppliers": []
                }

                # ------------------------------------------------
                # Tier-2 Path
                # ------------------------------------------------

                for tier2 in tier2_suppliers:

                    tier2_id = tier2[
                        "entity_id"
                    ]

                    tier2_name = tier2[
                        "name"
                    ]

                    # Event → Tier-2
                    path_result = session.execute_write(
                        connect_event_to_supplier_path,
                        event_id,
                        tier2_id,
                        tier1_id,
                        company_id
                    )

                    path = {

                        "tier2_supplier":
                            tier2_name,

                        "tier2_entity_id":
                            tier2_id,

                        "tier1_supplier":
                            tier1_name,

                        "tier1_entity_id":
                            tier1_id,

                        "company":
                            company_real_name,

                        "company_entity_id":
                            company_id
                    }

                    tier1_result[
                        "tier2_suppliers"
                    ].append(
                        path
                    )

                    article_result[
                        "supply_chain_paths"
                    ].append(
                        path
                    )

                    total_paths += 1

                    print(
                        f"      Path: "
                        f"{tier2_name}"
                        f" → "
                        f"{tier1_name}"
                        f" → "
                        f"{company_real_name}"
                    )

                company_result[
                    "tier1_suppliers"
                ].append(
                    tier1_result
                )

            article_result[
                "companies"
            ].append(
                company_result
            )

        agent2_results.append(
            article_result
        )


# ============================================================
# 20. Neo4j 종료
# ============================================================

driver.close()


# ============================================================
# 21. 결과 저장
# ============================================================

output_data = {

    "generated_at":
        datetime.now(
            timezone.utc
        ).isoformat(),

    "agent":
        "Agent 2",

    "description":
        (
            "Agent 1 news analysis results "
            "are connected to the existing "
            "supply chain knowledge graph."
        ),

    "summary": {

        "processed_events":
            len(agent2_results),

        "matched_companies":
            total_matched_companies,

        "tier1_supplier_count":
            total_tier1_suppliers,

        "tier2_supplier_count":
            total_tier2_suppliers,

        "supply_chain_path_count":
            total_paths
    },

    "results":
        agent2_results
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
# 22. 완료 로그
# ============================================================

print("\n" + "=" * 70)
print("Agent 2 완료")
print("=" * 70)

print(
    f"처리된 Event: "
    f"{len(agent2_results)}개"
)

print(
    f"Company 매칭 성공: "
    f"{total_matched_companies}개"
)

print(
    f"Tier-1 Supplier: "
    f"{total_tier1_suppliers}개"
)

print(
    f"Tier-2 Supplier: "
    f"{total_tier2_suppliers}개"
)

print(
    f"Supply Chain Path: "
    f"{total_paths}개"
)

print(
    f"결과 파일: "
    f"{OUTPUT_FILE}"
)


# ============================================================
# 23. 결과 검증
# ============================================================

if total_matched_companies == 0:

    print("\n" + "!" * 70)

    print(
        "WARNING: "
        "Company 매칭이 한 건도 성공하지 않았습니다."
    )

    print(
        "Neo4j의 Company 노드 Type/name을 확인해야 합니다."
    )

    print("!" * 70)


elif total_tier1_suppliers == 0:

    print("\n" + "!" * 70)

    print(
        "WARNING: "
        "Company는 매칭되었지만 "
        "Tier-1 Supplier가 없습니다."
    )

    print(
        "Neo4j의 Supplies 관계와 tier 값을 확인해야 합니다."
    )

    print("!" * 70)


else:

    print("\n✓ Agent 2 KG 연결 정상")

    print(
        "Event → Company → "
        "Tier-1 → Tier-2 구조가 생성되었습니다."
    )
