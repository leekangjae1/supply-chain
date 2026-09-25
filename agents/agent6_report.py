# ============================================================
# Agent 6 - Supply Chain Risk Decision Report
#
# Input:
#   agent5_risk_assessment.json
#
# Output:
#   agent6_final_report.json
#
# 역할:
#   Agent 5의 공급업체별 Risk Score 결과를 기반으로
#   사람이 의사결정을 할 수 있는 최종 보고서 생성
#
# 중요:
#   Agent 6에서는 Risk Score를 다시 계산하지 않는다.
#   Agent 5에서 계산된 값을 그대로 사용한다.
# ============================================================

import json
import os
from pathlib import Path
from openai import OpenAI


# ============================================================
# 1. 파일 경로
# ============================================================

INPUT_CANDIDATES = [
    Path("agent5_risk_assessment.json"),
    Path("data/agent5_risk_assessment.json"),
]

OUTPUT_FILE = Path("agent6_final_report.json")


# ============================================================
# 2. Agent 5 JSON 찾기
# ============================================================

def find_input_file():

    for path in INPUT_CANDIDATES:
        if path.exists():
            return path

    raise FileNotFoundError(
        "Agent 5 결과 파일을 찾을 수 없습니다.\n"
        "확인한 경로:\n"
        + "\n".join(str(p) for p in INPUT_CANDIDATES)
    )


# ============================================================
# 3. Agent 5 JSON 읽기
# ============================================================

def load_agent5_result():

    input_file = find_input_file()

    print("========================================")
    print("Agent 5 input")
    print("========================================")
    print(input_file)

    with open(input_file, "r", encoding="utf-8") as f:
        data = json.load(f)

    return data


# ============================================================
# 4. Agent 5 결과 구조 확인
# ============================================================

def validate_agent5_data(data):

    if not isinstance(data, dict):
        raise ValueError("Agent 5 JSON의 최상위 구조가 object가 아닙니다.")

    if "results" not in data:
        raise ValueError(
            "Agent 5 JSON에 'results' 필드가 없습니다."
        )

    if not isinstance(data["results"], list):
        raise ValueError(
            "Agent 5 JSON의 'results'가 list가 아닙니다."
        )

    if len(data["results"]) == 0:
        raise ValueError(
            "Agent 5 JSON의 results가 비어 있습니다."
        )


# ============================================================
# 5. 안전한 숫자 변환
# ============================================================

def safe_float(value, default=0.0):

    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def safe_int(value, default=0):

    try:
        return int(value)
    except (TypeError, ValueError):
        return default


# ============================================================
# 6. 공급업체 이름 가져오기
# ============================================================

def get_supplier_name(result):

    supplier = result.get("supplier")

    if supplier:
        return str(supplier)

    supplier_id = result.get("supplier_id")

    if supplier_id:
        return str(supplier_id)

    return "Unknown Supplier"


# ============================================================
# 7. Agent 5 결과 정리
# ============================================================

def normalize_results(results):

    normalized = []

    for item in results:

        supplier = get_supplier_name(item)

        normalized_item = {
            "supplier": supplier,

            "path_count": safe_int(
                item.get("path_count", 0)
            ),

            "products": item.get("products", [])
            if isinstance(item.get("products", []), list)
            else [],

            "companies": item.get("companies", [])
            if isinstance(item.get("companies", []), list)
            else [],

            "centrality": safe_float(
                item.get("centrality", 0)
            ),

            "exposure_breadth": safe_float(
                item.get("exposure_breadth", 0)
            ),

            "dependency_ratio": safe_float(
                item.get("dependency_ratio", 0)
            ),

            "exposure_depth": safe_float(
                item.get("exposure_depth", 0)
            ),

            "risk_score": safe_float(
                item.get("risk_score", 0)
            ),

            "risk_level": str(
                item.get("risk_level", "UNKNOWN")
            ),
        }

        normalized.append(normalized_item)

    return normalized


# ============================================================
# 8. Risk Level 집계
# ============================================================

def count_risk_levels(results):

    counts = {
        "HIGH": 0,
        "MEDIUM": 0,
        "LOW": 0,
        "UNKNOWN": 0
    }

    for item in results:

        level = str(
            item.get("risk_level", "UNKNOWN")
        ).upper()

        if level in counts:
            counts[level] += 1
        else:
            counts["UNKNOWN"] += 1

    return counts


# ============================================================
# 9. 최고 위험 공급업체 찾기
# ============================================================

def get_top_risks(results, top_n=10):

    sorted_results = sorted(
        results,
        key=lambda x: safe_float(
            x.get("risk_score", 0)
        ),
        reverse=True
    )

    return sorted_results[:top_n]


# ============================================================
# 10. MEDIUM / HIGH 위험 공급업체
# ============================================================

def get_attention_suppliers(results):

    attention = []

    for item in results:

        level = str(
            item.get("risk_level", "UNKNOWN")
        ).upper()

        if level in ["HIGH", "MEDIUM"]:
            attention.append(item)

    return sorted(
        attention,
        key=lambda x: safe_float(
            x.get("risk_score", 0)
        ),
        reverse=True
    )


# ============================================================
# 11. LLM에 전달할 Evidence Package 생성
# ============================================================

def build_evidence_package(agent5_data, results):

    risk_counts = count_risk_levels(results)

    top_risks = get_top_risks(results, top_n=10)

    attention_suppliers = get_attention_suppliers(results)

    package = {

        "agent5_method": agent5_data.get(
            "method",
            "Supplier-level risk assessment"
        ),

        "downstream_criticality": agent5_data.get(
            "downstream_criticality",
            False
        ),

        "weights": agent5_data.get(
            "weights",
            {}
        ),

        "supplier_count": agent5_data.get(
            "supplier_count",
            len(results)
        ),

        "risk_level_counts": risk_counts,

        "top_10_suppliers": top_risks,

        "attention_suppliers": attention_suppliers,

        "all_supplier_results": results
    }

    return package


# ============================================================
# 12. LLM Prompt
# ============================================================

def build_prompt(evidence_package):

    return f"""
당신은 공급망 리스크 분석 시스템의 Agent 6이다.

목적:
Agent 5가 계산한 공급업체별 Risk Assessment 결과를 바탕으로
사람이 공급망 대응 의사결정을 할 수 있도록 최종 보고서를 작성한다.

중요한 원칙:

1. Agent 5의 risk_score를 절대로 다시 계산하지 마라.
2. Agent 5의 risk_level을 임의로 변경하지 마라.
3. 제공된 데이터에 없는 뉴스, 사건, 기업 관계, 제품 관계를 만들어내지 마라.
4. products=[] 또는 companies=[]라고 해서 실제로 제품이나 기업 관계가 없다고 단정하지 마라.
   이는 KG 데이터가 없거나 관계가 충분히 확인되지 않았을 가능성이 있다.
5. dependency_ratio=0도 반드시 실제 의존도가 0이라고 단정하지 마라.
   데이터상 관계가 확인되지 않았다는 의미일 수 있으므로 검증 필요성을 제시할 수 있다.
6. Agent 5에는 뉴스 정보가 없으므로 특정 뉴스 사건을 만들어내지 마라.
7. 추천 행동은 '제안'으로 작성하고 이미 수행된 조치처럼 표현하지 마라.
8. Agent 5의 수치와 공급업체 이름은 가능한 한 그대로 유지하라.
9. 전체적인 판단은 Agent 5 결과에 근거해야 한다.
10. 보고서는 사람이 읽고 후속 조치를 판단할 수 있도록 작성한다.

Agent 5 방법론:

{json.dumps(
    evidence_package.get("agent5_method"),
    ensure_ascii=False
)}

Downstream Criticality 사용 여부:

{json.dumps(
    evidence_package.get("downstream_criticality"),
    ensure_ascii=False
)}

Agent 5 Weights:

{json.dumps(
    evidence_package.get("weights"),
    ensure_ascii=False,
    indent=2
)}

공급업체 수:

{evidence_package.get("supplier_count")}

Risk Level 집계:

{json.dumps(
    evidence_package.get("risk_level_counts"),
    ensure_ascii=False,
    indent=2
)}

상위 10개 공급업체:

{json.dumps(
    evidence_package.get("top_10_suppliers"),
    ensure_ascii=False,
    indent=2
)}

MEDIUM/HIGH 관심 공급업체:

{json.dumps(
    evidence_package.get("attention_suppliers"),
    ensure_ascii=False,
    indent=2
)}

전체 공급업체 결과:

{json.dumps(
    evidence_package.get("all_supplier_results"),
    ensure_ascii=False,
    indent=2
)}


반드시 아래 JSON 구조로만 출력하라.

{{
  "agent": "Agent 6",
  "report_type": "Supply Chain Risk Decision Report",

  "executive_summary": {{
    "overall_assessment": "",
    "highest_risk_supplier": "",
    "highest_risk_score": 0,
    "risk_level": "",
    "affected_companies": []
  }},

  "risk_assessment": {{
    "risk_score": 0,
    "risk_level": "",
    "exposure_breadth": 0,
    "dependency_ratio": 0,
    "centrality": 0,
    "exposure_depth": 0,
    "assessment_basis": ""
  }},

  "main_risk_factors": [],

  "affected_supply_chain": [
    {{
      "supplier": "",
      "connected_companies": [],
      "path_count": 0,
      "exposure_depth": 0,
      "risk_score": 0,
      "risk_level": ""
    }}
  ],

  "news_evidence": [],

  "risk_exposure_questions": [],

  "recommended_actions": {{
    "immediate": [],
    "short_term": [],
    "monitoring": []
  }},

  "data_quality_notes": [],

  "decision_summary": ""
}}

작성 규칙:

### executive_summary

전체 공급망 위험 수준을 설명한다.

최고 위험 공급업체는 Agent 5에서 가장 높은 risk_score를 가진 공급업체를 사용한다.

highest_risk_score와 risk_level은 Agent 5의 실제 값을 그대로 사용한다.

affected_companies는 최고 위험 공급업체의 companies 데이터를 사용한다.

### risk_assessment

최고 위험 공급업체의 Agent 5 수치를 그대로 입력한다.

다음 값을 임의로 변경하지 마라.

- risk_score
- risk_level
- exposure_breadth
- dependency_ratio
- centrality
- exposure_depth

### main_risk_factors

Agent 5의 지표를 기반으로 주요 위험 요인을 설명한다.

예:

- 높은 exposure breadth
- 높은 exposure depth
- 높은 centrality
- 높은 path count
- 상대적으로 높은 dependency ratio

단, 실제 데이터가 낮다면 높다고 표현하지 마라.

### affected_supply_chain

상위 위험 공급업체를 중심으로 작성한다.

각 공급업체에 대해:

- supplier
- connected_companies
- path_count
- exposure_depth
- risk_score
- risk_level

을 Agent 5 데이터에서 그대로 가져온다.

### news_evidence

Agent 5 데이터에는 뉴스 정보가 없으므로
뉴스를 만들어내지 마라.

빈 배열 []을 사용한다.

### risk_exposure_questions

사람이 추가로 확인해야 할 질문을 작성한다.

예:

- 해당 공급업체의 실제 생산 의존도는 어느 정도인가?
- 현재 KG에서 확인되지 않은 공급관계가 존재하는가?
- 대체 공급업체가 존재하는가?
- 공급 중단 시 영향을 받는 기업과 제품은 무엇인가?
- dependency_ratio가 0으로 계산된 이유가 실제 무관계인지 데이터 부족인지 확인할 필요가 있는가?

### recommended_actions

세 단계로 나눈다.

immediate:
현재 MEDIUM/HIGH 위험 공급업체의 관계 및 운영상태 확인 등

short_term:
대체 공급처, 공급망 경로, 재고 및 의존도 검토 등

monitoring:
Risk Score 변화, 공급업체 관계 변화, 신규 위험 정보 모니터링 등

단, 특정 사건이 발생했다고 가정하지 마라.

### data_quality_notes

다음과 같은 사항을 데이터 한계로 기록할 수 있다.

- companies가 비어 있는 공급업체
- products가 비어 있는 공급업체
- dependency_ratio가 0인 공급업체
- 뉴스 데이터가 Agent 5 입력에 포함되어 있지 않음

이것을 실제 공급망 관계가 없다는 의미로 단정하지 마라.

### decision_summary

사람이 최종적으로 무엇을 확인해야 하는지를 간결하게 정리한다.

다시 강조:

Agent 5의 수치를 변경하거나 새롭게 계산하지 마라.
"""


# ============================================================
# 13. OpenAI 호출
# ============================================================

def generate_report(evidence_package):

    api_key = os.getenv("OPENAI_API_KEY")

    if not api_key:
        raise EnvironmentError(
            "OPENAI_API_KEY 환경변수가 설정되어 있지 않습니다."
        )

    client = OpenAI(api_key=api_key)

    model = os.getenv(
        "OPENAI_MODEL",
        "gpt-5.6"
    )

    prompt = build_prompt(evidence_package)

    print("========================================")
    print("Running Agent 6")
    print("========================================")

    response = client.responses.create(
        model=model,
        input=prompt
    )

    output_text = response.output_text.strip()

    return output_text


# ============================================================
# 14. JSON 파싱
# ============================================================

def parse_json_output(output_text):

    try:
        return json.loads(output_text)

    except json.JSONDecodeError:

        # 혹시 ```json ... ``` 형태로 반환된 경우
        cleaned = output_text

        if cleaned.startswith("```json"):
            cleaned = cleaned[7:]

        if cleaned.startswith("```"):
            cleaned = cleaned[3:]

        if cleaned.endswith("```"):
            cleaned = cleaned[:-3]

        cleaned = cleaned.strip()

        try:
            return json.loads(cleaned)

        except json.JSONDecodeError as e:

            print("========================================")
            print("Agent 6 raw output")
            print("========================================")
            print(output_text)

            raise ValueError(
                f"Agent 6 출력이 올바른 JSON이 아닙니다: {e}"
            )


# ============================================================
# 15. Agent 5 수치와 Agent 6 결과 검증
# ============================================================

def validate_report(report, results):

    if not isinstance(report, dict):
        raise ValueError(
            "Agent 6 결과가 JSON object가 아닙니다."
        )

    required_fields = [
        "agent",
        "report_type",
        "executive_summary",
        "risk_assessment",
        "main_risk_factors",
        "affected_supply_chain",
        "news_evidence",
        "risk_exposure_questions",
        "recommended_actions",
        "data_quality_notes",
        "decision_summary"
    ]

    for field in required_fields:

        if field not in report:
            raise ValueError(
                f"Agent 6 결과에 '{field}' 필드가 없습니다."
            )

    # --------------------------------------------------------
    # Agent 5 최고 위험 공급업체
    # --------------------------------------------------------

    top_supplier = sorted(
        results,
        key=lambda x: safe_float(
            x.get("risk_score", 0)
        ),
        reverse=True
    )[0]

    expected_supplier = get_supplier_name(
        top_supplier
    )

    expected_score = safe_float(
        top_supplier.get("risk_score", 0)
    )

    expected_level = str(
        top_supplier.get("risk_level", "UNKNOWN")
    )

    # --------------------------------------------------------
    # Executive Summary 검증
    # --------------------------------------------------------

    executive = report.get(
        "executive_summary",
        {}
    )

    actual_supplier = executive.get(
        "highest_risk_supplier"
    )

    actual_score = safe_float(
        executive.get("highest_risk_score", 0)
    )

    actual_level = str(
        executive.get("risk_level", "")
    )

    # 공급업체 이름이 틀린 경우 수정
    if actual_supplier != expected_supplier:

        print(
            "WARNING: Agent 6 highest_risk_supplier mismatch."
        )

        executive[
            "highest_risk_supplier"
        ] = expected_supplier

    # Score는 Agent 5 값을 강제로 사용
    if actual_score != expected_score:

        print(
            "WARNING: Agent 6 highest_risk_score mismatch."
        )

        executive[
            "highest_risk_score"
        ] = expected_score

    # Risk Level은 Agent 5 값을 강제로 사용
    if actual_level != expected_level:

        print(
            "WARNING: Agent 6 risk_level mismatch."
        )

        executive[
            "risk_level"
        ] = expected_level

    # --------------------------------------------------------
    # Risk Assessment도 Agent 5 값으로 강제
    # --------------------------------------------------------

    assessment = report.get(
        "risk_assessment",
        {}
    )

    assessment[
        "risk_score"
    ] = expected_score

    assessment[
        "risk_level"
    ] = expected_level

    assessment[
        "exposure_breadth"
    ] = safe_float(
        top_supplier.get(
            "exposure_breadth",
            0
        )
    )

    assessment[
        "dependency_ratio"
    ] = safe_float(
        top_supplier.get(
            "dependency_ratio",
            0
        )
    )

    assessment[
        "centrality"
    ] = safe_float(
        top_supplier.get(
            "centrality",
            0
        )
    )

    assessment[
        "exposure_depth"
    ] = safe_float(
        top_supplier.get(
            "exposure_depth",
            0
        )
    )

    # --------------------------------------------------------
    # News evidence는 현재 Agent 5에 없으므로 비워둠
    # --------------------------------------------------------

    report["news_evidence"] = []

    return report


# ============================================================
# 16. JSON 저장
# ============================================================

def save_report(report):

    with open(
        OUTPUT_FILE,
        "w",
        encoding="utf-8"
    ) as f:

        json.dump(
            report,
            f,
            ensure_ascii=False,
            indent=2
        )

    print("========================================")
    print("Agent 6 completed")
    print("========================================")
    print(
        f"Output: {OUTPUT_FILE}"
    )


# ============================================================
# 17. Main
# ============================================================

def main():

    # --------------------------------------------------------
    # Agent 5 읽기
    # --------------------------------------------------------

    agent5_data = load_agent5_result()

    # --------------------------------------------------------
    # Agent 5 구조 검증
    # --------------------------------------------------------

    validate_agent5_data(
        agent5_data
    )

    # --------------------------------------------------------
    # 결과 정규화
    # --------------------------------------------------------

    results = normalize_results(
        agent5_data["results"]
    )

    print(
        f"Agent 5 suppliers: {len(results)}"
    )

    # --------------------------------------------------------
    # Evidence Package
    # --------------------------------------------------------

    evidence_package = build_evidence_package(
        agent5_data,
        results
    )

    # --------------------------------------------------------
    # Agent 6 LLM 실행
    # --------------------------------------------------------

    raw_output = generate_report(
        evidence_package
    )

    # --------------------------------------------------------
    # JSON 변환
    # --------------------------------------------------------

    report = parse_json_output(
        raw_output
    )

    # --------------------------------------------------------
    # Agent 5 결과와 검증
    # --------------------------------------------------------

    report = validate_report(
        report,
        results
    )

    # --------------------------------------------------------
    # 저장
    # --------------------------------------------------------

    save_report(
        report
    )


# ============================================================
# 실행
# ============================================================

if __name__ == "__main__":
    main()
