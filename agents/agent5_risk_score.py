
import json
import os
from collections import defaultdict
from pathlib import Path

import networkx as nx


# ============================================================
# 1. 설정
# ============================================================

INPUT_PATH = os.getenv(
    "AGENT2_KG_PATH",
    "data/agent2_kg.json"
)

OUTPUT_PATH = os.getenv(
    "AGENT5_OUTPUT_PATH",
    "data/agent5_risk_assessment.json"
)


# 논문 기반 사용 가중치
# Downstream Criticality는 제외하고 80%를 재정규화
WEIGHT_BREADTH = 0.35 / 0.80
WEIGHT_DEPENDENCY = 0.25 / 0.80
WEIGHT_CENTRALITY = 0.10 / 0.80
WEIGHT_DEPTH = 0.10 / 0.80

HIGH_THRESHOLD = 0.60
MEDIUM_THRESHOLD = 0.45


# ============================================================
# 2. KG JSON 불러오기
# ============================================================

def load_kg(path):
    print(f"[INFO] Loading KG: {path}")

    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)

    return data


# ============================================================
# 3. Neo4j Export JSON → 관계 데이터 변환
# ============================================================

def extract_relations(data):

    relations = []

    # Neo4j query 결과가 list인 경우
    if isinstance(data, list):

        for row in data:

            if not isinstance(row, dict):
                continue

            s = row.get("s")
            r = row.get("r")
            t = row.get("t")

            if not s or not r or not t:
                continue

            s_props = s.get("properties", {})
            r_props = r.get("properties", {})
            t_props = t.get("properties", {})

            source_name = (
                s_props.get("name")
                or r_props.get("source_name")
            )

            target_name = (
                t_props.get("name")
                or r_props.get("target_name")
            )

            source_type = (
                s_props.get("Type")
                or r_props.get("source_type")
            )

            target_type = (
                t_props.get("Type")
                or r_props.get("target_type")
            )

            relation_type = r_props.get("type")

            if not source_name or not target_name:
                continue

            relations.append({
                "source": source_name,
                "target": target_name,
                "source_type": source_type,
                "target_type": target_type,
                "relation_type": relation_type,
                "tier": str(r_props.get("tier", "")),
                "confidence": r_props.get("confidence"),
                "evidence": r_props.get("evidence")
            })

    return relations


# ============================================================
# 4. Supply Chain Graph 생성
# ============================================================

def build_supply_graph(relations):

    G = nx.DiGraph()

    for rel in relations:

        # Agent 5에서는 실제 공급 관계만 사용
        if rel["relation_type"] != "Supplies":
            continue

        source = rel["source"]
        target = rel["target"]

        G.add_node(
            source,
            Type=rel["source_type"]
        )

        G.add_node(
            target,
            Type=rel["target_type"]
        )

        G.add_edge(
            source,
            target,
            tier=rel["tier"],
            confidence=rel["confidence"]
        )

    return G


# ============================================================
# 5. Supplier 찾기
# ============================================================

def get_suppliers(G):

    suppliers = []

    for node, attrs in G.nodes(data=True):

        if attrs.get("Type") == "Supplier":
            suppliers.append(node)

    return suppliers


# ============================================================
# 6. Exposure Breadth
# ============================================================

def calculate_breadth(G, suppliers):

    path_counts = {}

    for supplier in suppliers:

        reachable = nx.descendants(G, supplier)

        # Company까지 연결되는 공급망 경로 수
        company_count = sum(
            1
            for node in reachable
            if G.nodes[node].get("Type") == "Company"
        )

        path_counts[supplier] = company_count

    max_count = max(path_counts.values(), default=0)

    breadth = {}

    for supplier in suppliers:

        if max_count == 0:
            breadth[supplier] = 0.0
        else:
            breadth[supplier] = (
                path_counts[supplier] / max_count
            )

    return breadth, path_counts


# ============================================================
# 7. Dependency Ratio
# ============================================================

def calculate_dependency(G, suppliers):

    dependency = {}

    for supplier in suppliers:

        direct_targets = list(
            G.successors(supplier)
        )

        if not direct_targets:
            dependency[supplier] = 0.0
            continue

        company_connections = 0

        for target in direct_targets:

            target_type = G.nodes[target].get("Type")

            # Supplier → Company
            if target_type == "Company":
                company_connections += 1

            # Supplier → Supplier → Company
            elif target_type == "Supplier":

                second_targets = list(
                    G.successors(target)
                )

                if any(
                    G.nodes[x].get("Type") == "Company"
                    for x in second_targets
                ):
                    company_connections += 1

        dependency[supplier] = min(
            company_connections / len(direct_targets),
            1.0
        )

    return dependency


# ============================================================
# 8. Centrality
# ============================================================

def calculate_centrality(G, suppliers):

    if len(G) == 0:
        return {s: 0.0 for s in suppliers}

    centrality_all = nx.degree_centrality(G)

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
            value = value / max_centrality

        result[supplier] = min(value, 1.0)

    return result


# ============================================================
# 9. Exposure Depth
# ============================================================

def calculate_depth(G, suppliers):

    depth = {}

    for supplier in suppliers:

        max_depth = 0

        try:

            lengths = nx.single_source_shortest_path_length(
                G,
                supplier
            )

            for node, distance in lengths.items():

                if node == supplier:
                    continue

                if G.nodes[node].get("Type") == "Company":
                    max_depth = max(
                        max_depth,
                        distance
                    )

        except Exception:
            max_depth = 0

        # 4단계를 최대 깊이로 정규화
        normalized = min(
            max_depth / 4.0,
            1.0
        )

        depth[supplier] = normalized

    return depth


# ============================================================
# 10. Risk Score
# ============================================================

def calculate_risk_score(
    breadth,
    dependency,
    centrality,
    depth
):

    score = (
        WEIGHT_BREADTH * breadth
        + WEIGHT_DEPENDENCY * dependency
        + WEIGHT_CENTRALITY * centrality
        + WEIGHT_DEPTH * depth
    )

    return min(max(score, 0.0), 1.0)


# ============================================================
# 11. Risk Level
# ============================================================

def get_risk_level(score):

    if score >= HIGH_THRESHOLD:
        return "HIGH"

    elif score >= MEDIUM_THRESHOLD:
        return "MEDIUM"

    return "LOW"


# ============================================================
# 12. 전체 분석
# ============================================================

def run_agent5():

    print("=" * 60)
    print("Agent 5 - Supply Chain Risk Assessment")
    print("=" * 60)

    # KG 로드
    data = load_kg(INPUT_PATH)

    # 관계 추출
    relations = extract_relations(data)

    print(
        f"[INFO] Total relations: {len(relations)}"
    )

    # 공급망 그래프
    G = build_supply_graph(relations)

    print(
        f"[INFO] Supply chain nodes: {G.number_of_nodes()}"
    )

    print(
        f"[INFO] Supply chain edges: {G.number_of_edges()}"
    )

    # Supplier
    suppliers = get_suppliers(G)

    print(
        f"[INFO] Suppliers: {len(suppliers)}"
    )

    if not suppliers:
        print("[WARNING] No Supplier nodes found.")

        return

    # 지표 계산
    breadth, path_counts = calculate_breadth(
        G,
        suppliers
    )

    dependency = calculate_dependency(
        G,
        suppliers
    )

    centrality = calculate_centrality(
        G,
        suppliers
    )

    depth = calculate_depth(
        G,
        suppliers
    )

    # 결과 생성
    results = []

    for supplier in suppliers:

        score = calculate_risk_score(
            breadth[supplier],
            dependency[supplier],
            centrality[supplier],
            depth[supplier]
        )

        risk_level = get_risk_level(score)

        results.append({

            "supplier": supplier,

            "exposure_breadth": round(
                breadth[supplier],
                4
            ),

            "dependency_ratio": round(
                dependency[supplier],
                4
            ),

            "centrality": round(
                centrality[supplier],
                4
            ),

            "exposure_depth": round(
                depth[supplier],
                4
            ),

            "risk_score": round(
                score,
                4
            ),

            "risk_level": risk_level
        })

    # 높은 위험도 순 정렬
    results.sort(
        key=lambda x: x["risk_score"],
        reverse=True
    )

    # 출력 데이터
    output = {

        "agent": "Agent 5",

        "description":
            "Supply Chain Risk Assessment based on Agent 2 Knowledge Graph",

        "weights": {

            "exposure_breadth":
                round(WEIGHT_BREADTH, 4),

            "dependency_ratio":
                round(WEIGHT_DEPENDENCY, 4),

            "centrality":
                round(WEIGHT_CENTRALITY, 4),

            "exposure_depth":
                round(WEIGHT_DEPTH, 4)

        },

        "thresholds": {

            "HIGH":
                HIGH_THRESHOLD,

            "MEDIUM":
                MEDIUM_THRESHOLD,

            "LOW":
                0.0
        },

        "results": results
    }

    # 출력 폴더 생성
    output_path = Path(OUTPUT_PATH)

    output_path.parent.mkdir(
        parents=True,
        exist_ok=True
    )

    # JSON 저장
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

    print()
    print(
        f"[SUCCESS] Saved: {output_path}"
    )

    print()
    print("Top Risk Suppliers")
    print("-" * 60)

    for result in results[:10]:

        print(
            f"{result['supplier']}: "
            f"{result['risk_score']:.4f} "
            f"({result['risk_level']})"
        )


# ============================================================
# 실행
# ============================================================

if __name__ == "__main__":
    run_agent5()
