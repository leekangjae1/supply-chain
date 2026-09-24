# ============================================================
# Agent 5 - Supply Chain Risk Score
# Downstream Criticality 제외
# ============================================================

import json
import os
import networkx as nx


# ============================================================
# 0. 설정
# ============================================================

INPUT_PATH = os.getenv(
    "AGENT2_KG_PATH",
    "data/agent2_results.json"
)

OUTPUT_PATH = "data/agent5_risk_assessment.json"


# ============================================================
# 1. Agent 2 결과 불러오기
# ============================================================

print("=" * 70)
print("Agent 5 - Supply Chain Risk Assessment")
print("=" * 70)

print(f"[INFO] Loading Agent 2 result: {INPUT_PATH}")

if not os.path.exists(INPUT_PATH):
    raise FileNotFoundError(
        f"Agent 2 result not found: {INPUT_PATH}"
    )

with open(INPUT_PATH, "r", encoding="utf-8") as f:
    agent2_data = json.load(f)


# ============================================================
# 2. Agent 2 결과에서 relations 추출
# ============================================================

relations = []


def add_relation(source, target, relation_type, tier=None):
    """
    NetworkX에 넣을 관계를 표준 형태로 저장
    """

    if not source or not target:
        return

    relations.append({
        "source": {
            "entity_id": source.get("entity_id") or source.get("name"),
            "name": source.get("name"),
            "type": source.get("type")
        },
        "target": {
            "entity_id": target.get("entity_id") or target.get("name"),
            "name": target.get("name"),
            "type": target.get("type")
        },
        "relation": {
            "type": relation_type,
            "tier": tier
        }
    })


# ------------------------------------------------------------
# Agent 2 결과의 results 확인
# ------------------------------------------------------------

if isinstance(agent2_data, dict):

    results = agent2_data.get("results", [])

elif isinstance(agent2_data, list):

    results = agent2_data

else:

    results = []


print(f"[INFO] Events found: {len(results)}")


# ============================================================
# 3. Agent 2 결과 → Relations
# ============================================================

for event_result in results:

    companies = event_result.get("companies", [])

    if not isinstance(companies, list):
        continue

    for company in companies:

        if not isinstance(company, dict):
            continue

        company_name = company.get("name")

        if not company_name:
            continue

        company_node = {
            "entity_id": company.get(
                "entity_id",
                company_name
            ),
            "name": company_name,
            "type": "Company"
        }


        # ----------------------------------------------------
        # Tier-1 Supplier
        # ----------------------------------------------------

        tier1_suppliers = company.get(
            "tier1_suppliers",
            []
        )

        if not isinstance(tier1_suppliers, list):
            continue


        for tier1 in tier1_suppliers:

            if not isinstance(tier1, dict):
                continue

            tier1_name = tier1.get("name")

            if not tier1_name:
                continue

            tier1_node = {
                "entity_id": tier1.get(
                    "entity_id",
                    tier1_name
                ),
                "name": tier1_name,
                "type": "Supplier"
            }


            # Tier-1 Supplier → Company

            add_relation(
                source=tier1_node,
                target=company_node,
                relation_type="Supplies",
                tier="Tier-1"
            )


            # ------------------------------------------------
            # Tier-2 Supplier
            # ------------------------------------------------

            tier2_suppliers = tier1.get(
                "tier2_suppliers",
                []
            )

            if not isinstance(tier2_suppliers, list):
                continue


            for tier2 in tier2_suppliers:

                if not isinstance(tier2, dict):
                    continue

                tier2_name = (
                    tier2.get("tier2_supplier")
                    or tier2.get("name")
                )

                if not tier2_name:
                    continue

                tier2_node = {
                    "entity_id": tier2.get(
                        "entity_id",
                        tier2_name
                    ),
                    "name": tier2_name,
                    "type": "Supplier"
                }


                # Tier-2 Supplier → Tier-1 Supplier

                add_relation(
                    source=tier2_node,
                    target=tier1_node,
                    relation_type="Supplies",
                    tier="Tier-2"
                )


print(
    f"[INFO] Relations extracted: {len(relations)}"
)


# ============================================================
# 4. NetworkX 그래프 생성
# ============================================================

G = nx.DiGraph()


for rel in relations:

    source = rel["source"]
    target = rel["target"]
    relation = rel["relation"]

    source_id = (
        source.get("entity_id")
        or source.get("name")
    )

    target_id = (
        target.get("entity_id")
        or target.get("name")
    )

    if not source_id or not target_id:
        continue


    G.add_node(
        source_id,
        name=source.get("name"),
        type=source.get("type")
    )


    G.add_node(
        target_id,
        name=target.get("name"),
        type=target.get("type")
    )


    G.add_edge(
        source_id,
        target_id,
        relation_type=relation.get("type"),
        tier=relation.get("tier")
    )


print("=" * 70)
print("Knowledge Graph 생성 완료")
print("=" * 70)

print(
    "Node 수:",
    G.number_of_nodes()
)

print(
    "Edge 수:",
    G.number_of_edges()
)


# ============================================================
# 5. Supplier 찾기
# ============================================================

supplier_nodes = []


for node, data in G.nodes(data=True):

    node_type = str(
        data.get("type", "")
    ).lower()

    if node_type == "supplier":

        supplier_nodes.append(node)


print(
    "Tier-1 Supplier 후보:",
    len(supplier_nodes)
)


# ============================================================
# 6. Degree Centrality
# ============================================================

centrality = nx.degree_centrality(G)


# ============================================================
# 7. Supplier별 기본 정보 계산
# ============================================================

supplier_info = {}


for supplier in supplier_nodes:

    supplier_name = G.nodes[supplier].get(
        "name",
        supplier
    )


    # Supplier가 직접 연결된 전체 관계

    neighbors = list(
        G.successors(supplier)
    )


    # 영향 경로 수

    path_count = len(neighbors)


    # Product

    products = []


    # Company

    companies = []


    for neighbor in neighbors:

        neighbor_data = G.nodes[neighbor]


        neighbor_type = str(
            neighbor_data.get(
                "type",
                ""
            )
        ).lower()


        edge_data = G.edges[
            supplier,
            neighbor
        ]


        relation_type = str(
            edge_data.get(
                "relation_type",
                ""
            )
        ).lower()


        if neighbor_type == "product":

            products.append(
                neighbor_data.get(
                    "name",
                    neighbor
                )
            )


        if neighbor_type == "company":

            companies.append(
                neighbor_data.get(
                    "name",
                    neighbor
                )
            )


    supplier_info[supplier] = {

        "supplier_id":
            supplier,

        "supplier_name":
            supplier_name,

        "path_count":
            path_count,

        "products":
            products,

        "companies":
            companies,

        "centrality":
            centrality.get(
                supplier,
                0
            )
    }


# ============================================================
# 8. Exposure Breadth
# ============================================================

max_path_count = max(
    [
        x["path_count"]
        for x in supplier_info.values()
    ],
    default=1
)


for supplier, info in supplier_info.items():

    info["exposure_breadth"] = (

        info["path_count"]
        / max_path_count

        if max_path_count > 0
        else 0
    )


# ============================================================
# 9. Dependency Ratio
# ============================================================

for supplier, info in supplier_info.items():

    total_components = len(
        info["products"]
    )


    if total_components == 0:

        info["dependency_ratio"] = 0


    else:

        # 현재 KG에서는
        # disruption-specific component 정보가 없으므로
        # 연결된 Product 전체를 노출 대상으로 간주

        info["dependency_ratio"] = 1.0


# ============================================================
# 10. Exposure Depth
# ============================================================

for supplier, info in supplier_info.items():

    max_depth = 1


    try:

        lengths = nx.single_source_shortest_path_length(
            G,
            supplier
        )


        if lengths:

            max_depth = max(
                lengths.values()
            )


    except Exception:

        max_depth = 1


    # --------------------------------------------------------
    # Tier-1 → 0.25
    # Tier-2 → 0.50
    # Tier-3 → 0.75
    # Tier-4 → 1.00
    # --------------------------------------------------------

    exposure_depth = (
        min(max_depth, 4)
        / 4
    )


    info["exposure_depth"] = (
        exposure_depth
    )


# ============================================================
# 11. Risk Score
# ============================================================

for supplier, info in supplier_info.items():

    raw_score = (

        0.35
        * info["exposure_breadth"]

        +

        0.25
        * info["dependency_ratio"]

        +

        0.10
        * info["centrality"]

        +

        0.10
        * info["exposure_depth"]

    )


    # --------------------------------------------------------
    # 현재 4개 항목의 가중치 합 = 0.80
    #
    # Breadth     0.35
    # Dependency  0.25
    # Centrality  0.10
    # Depth       0.10
    #
    # Total       0.80
    # --------------------------------------------------------

    risk_score = (
        raw_score / 0.80
    )


    info["risk_score"] = round(
        min(risk_score, 1.0),
        4
    )


# ============================================================
# 12. HIGH / MEDIUM / LOW
# ============================================================

for supplier, info in supplier_info.items():

    score = info["risk_score"]


    if score >= 0.60:

        risk_level = "HIGH"


    elif score >= 0.45:

        risk_level = "MEDIUM"


    else:

        risk_level = "LOW"


    info["risk_level"] = risk_level


# ============================================================
# 13. 결과 정렬
# ============================================================

risk_results = sorted(
    supplier_info.values(),
    key=lambda x: x["risk_score"],
    reverse=True
)


# ============================================================
# 14. 결과 출력
# ============================================================

print("=" * 70)
print("AGENT 5 RISK ASSESSMENT RESULT")
print("=" * 70)


for result in risk_results:

    print(
        f"{result['supplier_name']:<30}"
        f" Risk Score = "
        f"{result['risk_score']:.4f}"
        f"  Level = "
        f"{result['risk_level']}"
    )


# ============================================================
# 15. JSON 결과 생성
# ============================================================

output = {

    "agent":
        "Agent 5",

    "description":
        "Supply Chain Risk Score",

    "method":
        "Supplier-level risk assessment",

    "downstream_criticality":
        False,

    "weights": {

        "exposure_breadth":
            0.35,

        "dependency_ratio":
            0.25,

        "centrality":
            0.10,

        "exposure_depth":
            0.10
    },

    "weight_sum":
        0.80,

    "normalization":
        "risk_score = weighted_sum / 0.80",

    "thresholds": {

        "HIGH":
            ">= 0.60",

        "MEDIUM":
            ">= 0.45",

        "LOW":
            "< 0.45"
    },

    "supplier_count":
        len(risk_results),

    "results":
        risk_results
}


# ============================================================
# 16. 파일 저장
# ============================================================

os.makedirs(
    "data",
    exist_ok=True
)


with open(
    OUTPUT_PATH,
    "w",
    encoding="utf-8"
) as f:

    json.dump(
        output,
        f,
        ensure_ascii=False,
        indent=2
    )


# ============================================================
# 17. 완료
# ============================================================

print("=" * 70)

print(
    f"[SUCCESS] Agent 5 completed."
)

print(
    f"[SUCCESS] Output: {OUTPUT_PATH}"
)

print(
    f"[INFO] Risk suppliers: "
    f"{len(risk_results)}"
)

print("=" * 70)
