import os
import hashlib
import pandas as pd

from neo4j import GraphDatabase


# ============================================================
# 1. GitHub Secrets
# ============================================================

NEO4J_URI = os.environ["NEO4J_URI"]
NEO4J_USERNAME = os.environ["NEO4J_USERNAME"]
NEO4J_PASSWORD = os.environ["NEO4J_PASSWORD"]


# ============================================================
# 2. GitHub Repository 내부 파일 경로
# ============================================================

NODE_FILE = "data/neo4j_nodes.csv"

RELATIONSHIP_FILE = "data/neo4j_relationships.xlsx"


# ============================================================
# 3. 파일 읽기
# ============================================================

print("=" * 70)
print("KG 파일 읽기")
print("=" * 70)

nodes_df = pd.read_csv(
    NODE_FILE,
    encoding="utf-8-sig"
)

relationships_df = pd.read_excel(
    RELATIONSHIP_FILE
)

print(f"Node 개수         : {len(nodes_df)}")
print(f"Relationship 개수 : {len(relationships_df)}")


# ============================================================
# 4. 컬럼 확인
# ============================================================

required_node_columns = [
    "entity_id:ID(Entity)",
    "name",
    "type:LABEL",
    "source_files"
]

required_relationship_columns = [
    ":START_ID(Entity)",
    ":END_ID(Entity)",
    ":TYPE",
    "evidence",
    "source_file"
]


for column in required_node_columns:

    if column not in nodes_df.columns:
        raise ValueError(
            f"Node 컬럼 없음: {column}"
        )


for column in required_relationship_columns:

    if column not in relationships_df.columns:
        raise ValueError(
            f"Relationship 컬럼 없음: {column}"
        )


# ============================================================
# 5. Node dictionary
# ============================================================

node_map = {}

for _, row in nodes_df.iterrows():

    entity_id = str(
        row["entity_id:ID(Entity)"]
    ).strip()

    node_map[entity_id] = {
        "name": str(row["name"]).strip(),
        "type": str(row["type:LABEL"]).strip(),
        "source": str(row["source_files"]).strip()
    }


print(
    f"Node dictionary: {len(node_map)}개"
)


# ============================================================
# 6. Neo4j 연결
# ============================================================

print()
print("=" * 70)
print("Neo4j 연결")
print("=" * 70)

driver = GraphDatabase.driver(
    NEO4J_URI,
    auth=(
        NEO4J_USERNAME,
        NEO4J_PASSWORD
    )
)

driver.verify_connectivity()

print("Neo4j 연결 성공")


# ============================================================
# 7. Constraint
# ============================================================

def create_constraint(tx):

    tx.run("""
        CREATE CONSTRAINT entity_id_unique
        IF NOT EXISTS
        FOR (e:Entity)
        REQUIRE e.entity_id IS UNIQUE
    """)


with driver.session() as session:

    session.execute_write(
        create_constraint
    )


# ============================================================
# 8. Node 생성
# ============================================================

def create_node(
    tx,
    entity_id,
    name,
    node_type,
    source
):

    tx.run("""
        MERGE (n:Entity {
            entity_id: $entity_id
        })

        SET
            n.name = $name,
            n.Type = $node_type,
            n.source = $source
    """,
    entity_id=entity_id,
    name=name,
    node_type=node_type,
    source=source)


print()
print("=" * 70)
print("Node 생성")
print("=" * 70)


with driver.session() as session:

    for i, (entity_id, data) in enumerate(
        node_map.items(),
        start=1
    ):

        session.execute_write(
            create_node,
            entity_id,
            data["name"],
            data["type"],
            data["source"]
        )

        if i % 50 == 0:
            print(
                f"Node: {i}/{len(node_map)}"
            )


print(
    f"Node 생성 완료: {len(node_map)}개"
)


# ============================================================
# 9. Relation ID
# ============================================================

def make_relation_id(
    start_id,
    end_id,
    relation_type,
    evidence
):

    raw = (
        f"{start_id}|"
        f"{end_id}|"
        f"{relation_type}|"
        f"{evidence}"
    )

    return (
        "REL_" +
        hashlib.sha256(
            raw.encode("utf-8")
        ).hexdigest()[:16]
    )


# ============================================================
# 10. Tier 계산
# ============================================================

def calculate_tier(
    relation_type,
    target_type
):

    if relation_type != "Supplies":
        return None

    if target_type == "Company":
        return "1"

    if target_type == "Supplier":
        return "2"

    return None


# ============================================================
# 11. Relationship 생성
# ============================================================

def create_relationship(
    tx,
    start_id,
    end_id,
    relation_id,
    relation_type,
    evidence,
    source_file,
    source_name,
    target_name,
    source_type,
    target_type,
    tier
):

    tx.run("""
        MATCH (s:Entity {
            entity_id: $start_id
        })

        MATCH (t:Entity {
            entity_id: $end_id
        })

        MERGE (s)-[
            r:KG_RELATION {
                relation_id: $relation_id
            }
        ]->(t)

        SET
            r.type = $relation_type,
            r.evidence = $evidence,
            r.source_file = $source_file,
            r.source_name = $source_name,
            r.target_name = $target_name,
            r.source_type = $source_type,
            r.target_type = $target_type,
            r.tier = $tier
    """,
    start_id=start_id,
    end_id=end_id,
    relation_id=relation_id,
    relation_type=relation_type,
    evidence=evidence,
    source_file=source_file,
    source_name=source_name,
    target_name=target_name,
    source_type=source_type,
    target_type=target_type,
    tier=tier)


# ============================================================
# 12. Relationship 업로드
# ============================================================

print()
print("=" * 70)
print("Relationship 생성")
print("=" * 70)


success_count = 0
skip_count = 0


with driver.session() as session:

    for _, row in relationships_df.iterrows():

        start_id = str(
            row[":START_ID(Entity)"]
        ).strip()

        end_id = str(
            row[":END_ID(Entity)"]
        ).strip()

        relation_type = str(
            row[":TYPE"]
        ).strip()

        evidence = str(
            row["evidence"]
        ).strip()

        source_file = str(
            row["source_file"]
        ).strip()


        # Node 존재 확인

        if start_id not in node_map:

            print(
                f"[SKIP] 시작 Node 없음: {start_id}"
            )

            skip_count += 1
            continue


        if end_id not in node_map:

            print(
                f"[SKIP] 종료 Node 없음: {end_id}"
            )

            skip_count += 1
            continue


        source_node = node_map[start_id]
        target_node = node_map[end_id]


        source_name = source_node["name"]
        target_name = target_node["name"]

        source_type = source_node["type"]
        target_type = target_node["type"]


        tier = calculate_tier(
            relation_type,
            target_type
        )


        relation_id = make_relation_id(
            start_id,
            end_id,
            relation_type,
            evidence
        )


        session.execute_write(
            create_relationship,
            start_id,
            end_id,
            relation_id,
            relation_type,
            evidence,
            source_file,
            source_name,
            target_name,
            source_type,
            target_type,
            tier
        )


        success_count += 1


        if success_count % 100 == 0:

            print(
                f"Relationship: "
                f"{success_count}/"
                f"{len(relationships_df)}"
            )


# ============================================================
# 13. 최종 결과
# ============================================================

def get_counts(tx):

    result = tx.run("""
        MATCH (n:Entity)
        WITH count(n) AS nodes

        OPTIONAL MATCH ()-[r:KG_RELATION]->()

        RETURN
            nodes,
            count(r) AS relationships
    """)

    return result.single()


def get_supplies(tx):

    result = tx.run("""
        MATCH ()-[r:KG_RELATION]->()

        WHERE r.type = 'Supplies'

        RETURN count(r) AS count
    """)

    return result.single()["count"]


def get_tier1(tx):

    result = tx.run("""
        MATCH ()-[r:KG_RELATION]->(c:Entity)

        WHERE r.type = 'Supplies'
        AND r.tier = '1'
        AND c.Type = 'Company'

        RETURN count(r) AS count
    """)

    return result.single()["count"]


def get_tier2(tx):

    result = tx.run("""
        MATCH ()-[r:KG_RELATION]->(s:Entity)

        WHERE r.type = 'Supplies'
        AND r.tier = '2'
        AND s.Type = 'Supplier'

        RETURN count(r) AS count
    """)

    return result.single()["count"]


with driver.session() as session:

    counts = session.execute_read(
        get_counts
    )

    supplies = session.execute_read(
        get_supplies
    )

    tier1 = session.execute_read(
        get_tier1
    )

    tier2 = session.execute_read(
        get_tier2
    )


print()
print("=" * 70)
print("최종 결과")
print("=" * 70)

print(
    f"Entity Node       : {counts['nodes']}"
)

print(
    f"KG_RELATION       : {counts['relationships']}"
)

print(
    f"Supplies          : {supplies}"
)

print(
    f"Tier 1            : {tier1}"
)

print(
    f"Tier 2            : {tier2}"
)

print(
    f"업로드 성공       : {success_count}"
)

print(
    f"건너뛴 관계       : {skip_count}"
)


driver.close()

print()
print("KG 업로드 완료!")
