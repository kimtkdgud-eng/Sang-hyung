"""DOE 후보 제약 검토. Pareto 선정 앞단에서 조성 규칙을 통과한 후보만 남긴다.

통과한 후보도 자동 승인하지 않는다: status='pending_researcher_approval' 로만 표시하고 승인은 연구자가 한다.
"""
from .composition import validate


def screen(candidates, rules):
    """candidates: [{"id":..., "components":[{component_class,name,amount,unit,basis}, ...]}]."""
    passed, rejected = [], []
    for cand in candidates:
        issues = validate(cand["components"], rules)
        if issues:
            rejected.append({"id": cand["id"], "issues": issues})
        else:
            passed.append({"id": cand["id"], "status": "pending_researcher_approval"})
    return {"passed": passed, "rejected": rejected,
            "note": "통과는 조성 규칙(단위·합계·범위·허용 목록)만 확인한 것이다. 성능·안전·제조 가능성 검증이 아니며 연구자 승인이 필요하다."}


def to_markdown(result):
    lines = [f"- 통과 {len(result['passed'])}개 (모두 연구자 승인 대기), 제외 {len(result['rejected'])}개", ""]
    for r in result["rejected"]:
        lines.append(f"- **{r['id']}** 제외: " + "; ".join(f"[{c}] {m}" for c, m in r["issues"]))
    return "\n".join(lines) + "\n\n" + result["note"] + "\n"
