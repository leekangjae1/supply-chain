import json
import os
from pathlib import Path

import networkx as nx


# ============================================================
# 1. 파일 설정
# ============================================================

INPUT_PATH = os.getenv(
    "AGENT2_KG_PATH",
    "data/agent2_kg.json"
)

OUTPUT_PATH = os.getenv(
    "AGENT5_OUTPUT_PATH",
    "data/agent5_risk_assessment.json"
)


# ============================================================
# 2. Risk Score 가중치
# ============================================================
#
# 기존 설정:
#
# Breadth       = 35%
# Dependency    = 25%
# Downstream    = 20%  → 현재 사용하지 않음
# Centrality    = 10%
# Depth         = 10%
#
# Downstream Criticality 20%를 제외하고
# 나머지 80%를 100%로 재정규화
#
# 최종:
# Breadth       = 43.75%
# Dependency    = 31.25%
# Centrality    = 12.50%
# Depth         = 12.50%
# ============================================================

WEIGHT_BREADTH = 0.35 / 0.80
WEIGHT_DEPENDENCY = 0.25 / 0.80
WEIGHT_CENTRALITY = 0.10 / 0.80
WEIGHT_DEPTH = 0.10 / 0.80


# ============================================================
# 3. Risk Level 기준
# ============================================================

HIGH_THRESHOLD = 0.60
MEDIUM_THRESHOLD = 0.45


# ============================================================
# 4. JSON Load
# ============================================================

def load_kg(path):

    print(f"[INFO] Loading Agent 2 result: {path}")

    if not os.path.exists(path):

        raise FileNotFoundError(
            f"Agent 2 결과 파일이 없습니다: {path}"
        )

    with open(
        path,
        "r",
        encoding="utf-8"
    ) as f:

        return json.load(f)


# ============================================================
# 5. Agent 2 JSON → Supply Chain Relations
# ============================================================

def extract_agent2_relations(data):

    """
    현재 Agent 2 결과 구조:

    {
      "generated_at": "...",
      "agent": "Agent 2",
      "description": "...",
      "results": [
        {
          "event_id": "...",
          "event": "...",
          "disruption_type": "...",

          "companies": [
            {
              "name": "...",
              "matched": true,

              "tier1_suppliers": [
                {
                  "name": "...",

                  "tier2_suppliers": [
                    {
                      "tier2_supplier": "..."
                    }
                  ]
                }
              ]
            }
          ]
        }
      ]
    }

    Agent 5에서 사용할 관계:

        Tier-1 Supplier
              ↓
           Company

        Tier-2 Supplier
              ↓
        Tier-1 Supplier

    """

    relations = []

    events = []

    if isinstance(data, dict):

        results = data.get(
            "results",
            []
        )

    elif isinstance(data, list):

        results = data

    else:

        results = []

    if not isinstance(results, list):

        results = [results]


    # ========================================================
    # Event 단위 처리
    # ========================================================

    for event_result in results:

        if not isinstance(
            event_result,
            dict
        ):
            continue


        event_id = event_result.get(
            "event_id",
            ""
        )

        event_name = event_result.get(
            "event",
            ""
        )

        disruption_type = event_result.get(
            "disruption_type",
            ""
        )


        events.append({

            "event_id": event_id,

            "event": event_name,

            "disruption_type":
                disruption_type

        })


        # ====================================================
        # Companies
        # ====================================================

        companies = event_result.get(
            "companies",
            []
        )

        if not isinstance(
            companies,
            list
        ):
            continue


        for company in companies:

            if not isinstance(
                company,
                dict
            ):
                continue


            # Company 매칭 실패 제외
            if company.get(
                "matched"
            ) is False:

                continue


            company_name = company.get(
                "name"
            )

            if not company_name:

                continue


            # =================================================
            # Tier 1
            # =================================================

            tier1_suppliers = company.get(
                "tier1_suppliers",
                []
            )

            if not isinstance(
                tier1_suppliers,
                list
            ):
                continue


            for tier1 in tier1_suppliers:

                if not isinstance(
                    tier1,
                    dict
                ):
                    continue


                tier1_name = tier1.get(
                    "name"
                )

                if not tier1_name:

                    continue


                # ---------------------------------------------
                # Tier-1 Supplier → Company
                # ---------------------------------------------

                relations.append({

                    "source":
                        tier1_name,

                    "target":
                        company_name,

                    "source_type":
                        "Supplier",

                    "target_type":
                        "Company",

                    "relation_type":
                        "Supplies",

                    "tier":
                        "Tier-1",

                    "event_id":
                        event_id,

                    "event":
                        event_name,

                    "disruption_type":
                        disruption_type

                })


                # =================================================
                # Tier 2
                # =================================================

                tier2_suppliers = tier1.get(
                    "tier2_suppliers",
                    []
                )

                if not isinstance(
                    tier2_suppliers,
                    list
                ):
                    continue


                for tier2 in tier2_suppliers:

                    if not isinstance(
                        tier2,
                        dict
                    ):
                        continue


                    tier2_name = tier2.get(
                        "tier2_supplier"
                    )

                    if not tier2_name:

                        continue


                    # ---------------------------------------------
                    # Tier-2 Supplier → Tier-1 Supplier
                    # ---------------------------------------------

                    relations.append({

                        "source":
                            tier2_name,

                        "target":
                            tier1_name,

                        "source_type":
                            "Supplier",

                        "target_type":
                            "Supplier",

                        "relation_type":
                            "Supplies",

                        "tier":
                            "Tier-2",

                        "event_id":
                            event_id,

                        "event":
                            event_name,

                        "disruption_type":
                            disruption_type

                    })


    print(
        "[INFO] Input format: Agent 2 results"
    )

    print(
        f"[INFO] Events found: {len(events)}"
    )

    print(
        f"[INFO] Relations extracted: "
        f"{len(relations)}"
    )

    return relations, events


# ============================================================
# 6. 기존 Neo4j Export도 지원
# ============================================================

def extract_neo4j_relations(data):

    """
    기존 Neo4j export 형식:

    [
      {
        "s": {...},
        "r": {...},
        "t": {...}
      }
    ]

    """

    relations = []


    if not isinstance(
        data,
        list
    ):

        return relations


    for row in data:

        if not isinstance(
            row,
            dict
        ):
            continue


        s = row.get("s")

        r = row.get("r")

        t = row.get("t")


        if not s or not r or not t:

            continue


        s_props = s.get(
            "properties",
            {}
        )

        r_props = r.get(
            "properties",
            {}
        )

        t_props = t.get(
            "properties",
            {}
        )


        source_name = (

            s_props.get("name")

            or r_props.get(
                "source_name"
            )

        )


        target_name = (

            t_props.get("name")

            or r_props.get(
                "target_name"
            )

        )


        source_type = (

            s_props.get("Type")

            or r_props.get(
                "source_type"
            )

        )


        target_type = (

            t_props.get("Type")

            or r_props.get(
                "target_type"
            )

        )


        relation_type = r_props.get(
            "type"
        )


        if not source_name:

            continue


        if not target_name:

            continue


        relations.append({

            "source":
                source_name,

            "target":
                target_name,

            "source_type":
                source_type,

            "target_type":
                target_type,

            "relation_type":
                relation_type,

            "tier":
                str(
                    r_props.get(
                        "tier",
                        ""
                    )
                ),

            "confidence":
                r_props.get(
                    "confidence"
                ),

            "evidence":
                r_props.get(
                    "evidence"
                )

        })


    print(
        "[INFO] Input format: Neo4j export"
    )

    print(
        f"[INFO] Relations extracted: "
        f"{len(relations)}"
    )

    return relations, []


# ============================================================
# 7. 입력 형식 자동 판별
# ============================================================

def extract_relations(data):

    # Agent 2 결과
    if (
        isinstance(data, dict)
        and "results" in data
    ):

        return extract_agent2_relations(
            data
        )


    # 기존 Neo4j export
    if isinstance(
        data,
        list
    ):

        return extract_neo4j_relations(
            data
        )


    print(
        "[WARNING] Unknown JSON structure."
    )

    return [], []


# ============================================================
# 8. Supply Chain Graph
# ============================================================

def build_supply_graph(
    relations
):

    G = nx.DiGraph()


    for rel in relations:

        if rel.get(
            "relation_type"
        ) != "Supplies":

            continue


        source = rel.get(
            "source"
        )

        target = rel.get(
            "target"
        )


        if not source or not target:

            continue


        source_type = rel.get(
            "source_type"
        )

        target_type = rel.get(
            "target_type"
        )

        tier = rel.get(
            "tier",
            ""
        )


        # =====================================================
        # Source Node
        # =====================================================

        if source not in G:

            G.add_node(

                source,

                Type=source_type,

                Tier=(
                    tier
                    if source_type == "Supplier"
                    else None
                )

            )

        else:

            # Supplier인데 기존 Tier가 없으면 보완
            if (
                source_type == "Supplier"
                and not G.nodes[source].get(
                    "Tier"
                )
            ):

                G.nodes[source]["Tier"] = tier


        # =====================================================
        # Target Node
        # =====================================================

        if target not in G:

            G.add_node(

                target,

                Type=target_type,

                Tier=None

            )


        # =====================================================
        # Edge
        # =====================================================

        G.add_edge(

            source,

            target,

            tier=tier,

            event_id=rel.get(
                "event_id"
            ),

            event=rel.get(
                "event"
            ),

            disruption_type=rel.get(
                "disruption_type"
            )

        )


    return G


# ============================================================
# 9. Tier-1 Supplier 추출
# ============================================================

def get_suppliers(
    G,
    relations
):

    """
    Agent 2 결과에서는 relation의 tier가
    가장 확실한 기준이다.

    따라서 Tier-1 relation의 source를
    최종 Risk Assessment 대상으로 사용한다.
    """

    suppliers = set()


    for rel in relations:

        if (
            rel.get("tier")
            == "Tier-1"
            and rel.get("source_type")
            == "Supplier"
        ):

            source = rel.get(
                "source"
            )

            if source:

                suppliers.add(
                    source
                )


    return sorted(
        suppliers
    )


# ============================================================
# 10. Exposure Breadth
# ============================================================

def calculate_breadth(
    G,
    suppliers
):

    """
    Supplier가 downstream으로
    몇 개의 Company에 연결되는지 계산.

    최대 Company 수를 1로 정규화.
    """

    company_counts = {}


    for supplier in suppliers:

        try:

            reachable = nx.descendants(
                G,
                supplier
            )

        except Exception:

            reachable = set()


        company_count = 0


        for node in reachable:

            if (
                G.nodes[node].get(
                    "Type"
                )
                == "Company"
            ):

                company_count += 1


        company_counts[
            supplier
        ] = company_count


    max_count = max(
        company_counts.values(),
        default=0
    )


    breadth = {}


    for supplier in suppliers:

        if max_count == 0:

            breadth[supplier] = 0.0

        else:

            breadth[supplier] = (
                company_counts[supplier]
                / max_count
            )


    return breadth, company_counts


# ============================================================
# 11. Dependency Ratio
# ============================================================

def calculate_dependency(
    G,
    suppliers
):

    """
    직접 연결된 downstream node를 기준으로
    Company 연결 여부를 계산한다.

    Tier-1:
        Supplier → Company

    Tier-2:
        Supplier → Tier-1 Supplier → Company

    """

    dependency = {}


    for supplier in suppliers:

        direct_targets = list(
            G.successors(
                supplier
            )
        )


        if not direct_targets:

            dependency[supplier] = 0.0

            continue


        company_connections = 0


        for target in direct_targets:

            target_type = G.nodes[
                target
            ].get("Type")


            # ----------------------------------------------
            # Supplier → Company
            # ----------------------------------------------

            if target_type == "Company":

                company_connections += 1


            # ----------------------------------------------
            # Supplier → Supplier → Company
            # ----------------------------------------------

            elif target_type == "Supplier":

                second_targets = list(
                    G.successors(
                        target
                    )
                )


                if any(

                    G.nodes[x].get(
                        "Type"
                    )
                    == "Company"

                    for x
                    in second_targets

                ):

                    company_connections += 1


        dependency[supplier] = min(

            company_connections
            / len(direct_targets),

            1.0

        )


    return dependency


# ============================================================
# 12. Centrality
# ============================================================

def calculate_centrality(
    G,
    suppliers
):

    if len(G) == 0:

        return {
            supplier: 0.0
            for supplier in suppliers
        }


    centrality_all = (
        nx.degree_centrality(G)
    )


    max_centrality = max(

        centrality_all.values(),

        default=0

    )


    result = {}


    for supplier in suppliers:

        value = centrality_all.get(
            supplier,
            0.0
        )


        if max_centrality > 0:

            value = (
                value
                / max_centrality
            )


        result[supplier] = min(
            value,
            1.0
        )


    return result


# ============================================================
# 13. Exposure Depth
# ============================================================

def calculate_depth(
    G,
    suppliers
):

    """
    Supplier → Company의
    shortest path 최대값.

    Tier 구조:
        Tier-1 → Company = 1
        Tier-2 → Tier-1 → Company = 2

    최대 Tier-4를 1.0으로 정규화.
    """

    depth = {}


    for supplier in suppliers:

        max_depth = 0


        try:

            lengths = (
                nx.single_source_shortest_path_length(
                    G,
                    supplier
                )
            )


            for node, distance in lengths.items():

                if node == supplier:

                    continue


                if (
                    G.nodes[node].get(
                        "Type"
                    )
                    == "Company"
                ):

                    max_depth = max(
                        max_depth,
                        distance
                    )


        except Exception:

            max_depth = 0


        normalized = min(

            max_depth / 4.0,

            1.0

        )


        depth[supplier] = normalized


    return depth


# ============================================================
# 14. Risk Score
# ============================================================

def calculate_risk_score(

    breadth,

    dependency,

    centrality,

    depth

):

    score = (

        WEIGHT_BREADTH
        * breadth

        +

        WEIGHT_DEPENDENCY
        * dependency

        +

        WEIGHT_CENTRALITY
        * centrality

        +

        WEIGHT_DEPTH
        * depth

    )


    return min(

        max(
            score,
            0.0
        ),

        1.0

    )


# ============================================================
# 15. Risk Level
# ============================================================

def get_risk_level(
    score
):

    if score >= HIGH_THRESHOLD:

        return "HIGH"


    elif score >= MEDIUM_THRESHOLD:

        return "MEDIUM"


    return "LOW"


# ============================================================
# 16. Agent 5 실행
# ============================================================

def run_agent5():

    print()
    print("=" * 60)
    print("Agent 5 - Supply Chain Risk Assessment")
    print("=" * 60)
    print()


    # ========================================================
    # Step 1. Agent 2 결과 불러오기
    # ========================================================

    data = load_kg(
        INPUT_PATH
    )


    # ========================================================
    # Step 2. 관계 추출
    # ========================================================

    (
        relations,
        events
    ) = extract_relations(
        data
    )


    print(
        f"[INFO] Total relations: "
        f"{len(relations)}"
    )


    # ========================================================
    # Step 3. Graph 생성
    # ========================================================

    G = build_supply_graph(
        relations
    )


    print(
        f"[INFO] Supply chain nodes: "
        f"{G.number_of_nodes()}"
    )


    print(
        f"[INFO] Supply chain edges: "
        f"{G.number_of_edges()}"
    )


    # ========================================================
    # Step 4. Tier-1 Supplier 추출
    # ========================================================

    suppliers = get_suppliers(
        G,
        relations
    )


    print(
        f"[INFO] Tier-1 suppliers: "
        f"{len(suppliers)}"
    )


    # ========================================================
    # Supplier가 없는 경우
    # ========================================================

    if not suppliers:

        print(
            "[WARNING] No Tier-1 Supplier found."
        )


        output = {

            "agent":
                "Agent 5",

            "description":
                "Supply Chain Risk Assessment",

            "events":
                events,

            "weights": {

                "exposure_breadth":
                    round(
                        WEIGHT_BREADTH,
                        4
                    ),

                "dependency_ratio":
                    round(
                        WEIGHT_DEPENDENCY,
                        4
                    ),

                "centrality":
                    round(
                        WEIGHT_CENTRALITY,
                        4
                    ),

                "exposure_depth":
                    round(
                        WEIGHT_DEPTH,
                        4
                    )

            },

            "thresholds": {

                "HIGH":
                    HIGH_THRESHOLD,

                "MEDIUM":
                    MEDIUM_THRESHOLD,

                "LOW":
                    0.0

            },

            "results": []

        }


        output_path = Path(
            OUTPUT_PATH
        )


        output_path.parent.mkdir(
            parents=True,
            exist_ok=True
        )


        with open(

            output_path,

            "w",

            encoding="utf-8"

        ) as f:

            json.dump(

                output,

                f,

                ensure_ascii=False,

                indent=2

            )


        return


    # ========================================================
    # Step 5. Breadth
    # ========================================================

    breadth, company_counts = (
        calculate_breadth(
            G,
            suppliers
        )
    )


    # ========================================================
    # Step 6. Dependency
    # ========================================================

    dependency = calculate_dependency(

        G,

        suppliers

    )


    # ========================================================
    # Step 7. Centrality
    # ========================================================

    centrality = calculate_centrality(

        G,

        suppliers

    )


    # ========================================================
    # Step 8. Depth
    # ========================================================

    depth = calculate_depth(

        G,

        suppliers

    )


    # ========================================================
    # Step 9. Risk Score
    # ========================================================

    results = []


    for supplier in suppliers:

        score = calculate_risk_score(

            breadth[supplier],

            dependency[supplier],

            centrality[supplier],

            depth[supplier]

        )


        risk_level = get_risk_level(
            score
        )


        results.append({

            "supplier":
                supplier,

            "exposure_breadth":
                round(
                    breadth[supplier],
                    4
                ),

            "dependency_ratio":
                round(
                    dependency[supplier],
                    4
                ),

            "centrality":
                round(
                    centrality[supplier],
                    4
                ),

            "exposure_depth":
                round(
                    depth[supplier],
                    4
                ),

            "risk_score":
                round(
                    score,
                    4
                ),

            "risk_level":
                risk_level,

            "affected_company_count":
                company_counts.get(
                    supplier,
                    0
                )

        })


    # ========================================================
    # Step 10. 위험도 높은 순 정렬
    # ========================================================

    results.sort(

        key=lambda x:
            x["risk_score"],

        reverse=True

    )


    # ========================================================
    # Step 11. 최종 JSON
    # ========================================================

    output = {

        "agent":
            "Agent 5",

        "description":
            "Supply Chain Risk Assessment based on Agent 2 Knowledge Graph",

        "input":
            INPUT_PATH,

        "events":
            events,

        "weights": {

            "exposure_breadth":
                round(
                    WEIGHT_BREADTH,
                    4
                ),

            "dependency_ratio":
                round(
                    WEIGHT_DEPENDENCY,
                    4
                ),

            "centrality":
                round(
                    WEIGHT_CENTRALITY,
                    4
                ),

            "exposure_depth":
                round(
                    WEIGHT_DEPTH,
                    4
                )

        },

        "thresholds": {

            "HIGH":
                HIGH_THRESHOLD,

            "MEDIUM":
                MEDIUM_THRESHOLD,

            "LOW":
                0.0

        },

        "results":
            results

    }


    # ========================================================
    # Step 12. JSON 저장
    # ========================================================

    output_path = Path(
        OUTPUT_PATH
    )


    output_path.parent.mkdir(
        parents=True,
        exist_ok=True
    )


    with open(

        output_path,

        "w",

        encoding="utf-8"

    ) as f:

        json.dump(

            output,

            f,

            ensure_ascii=False,

            indent=2

        )


    # ========================================================
    # Step 13. 로그
    # ========================================================

    print()
    print(
        "=" * 60
    )

    print(
        "[SUCCESS] Agent 5 completed."
    )

    print(
        f"[SUCCESS] Output: "
        f"{output_path}"
    )

    print(
        f"[INFO] Risk suppliers: "
        f"{len(results)}"
    )

    print(
        "=" * 60
    )


    print()
    print(
        "Top Risk Suppliers"
    )

    print(
        "-" * 60
    )


    for result in results[:10]:

        print(

            f"{result['supplier']} | "

            f"Score: "
            f"{result['risk_score']:.4f} | "

            f"Level: "
            f"{result['risk_level']}"

        )


# ============================================================
# Main
# ============================================================

if __name__ == "__main__":

    run_agent5()
