"""조성 표기 규칙과 검증 (허브 계약·DOE 제약 검토가 함께 쓴다).

사내 표기 규칙: 염 = mol/L(M), 용매 = vol%, 첨가제 = wt%.
  - 합계 100 닫힘은 용매 vol% 에만 적용한다. 염과 첨가제는 그 합계 밖에서 각자의 범위로 확인한다.
  - 단위는 조용히 환산하지 않는다(v2.12 원칙). 규칙과 다른 단위는 위반으로 보고한다.
  - 범위·허용 목록·비호환 쌍은 회사 값이다 -> configs/composition_rules.example.json 은 예시일 뿐이다.
"""
import json
from dataclasses import dataclass, field


@dataclass
class Rules:
    unit_by_class: dict = field(default_factory=lambda: {"salt": "mol/L", "solvent": "vol%", "additive": "wt%"})
    basis_by_class: dict = field(default_factory=dict)      # 예: {"additive": "total_electrolyte"}; 없으면 기준 미검사
    solvent_sum: float = 100.0
    solvent_tol: float = 0.5
    ranges: dict = field(default_factory=dict)              # "class::name" -> [min, max]
    additive_total_max: float = None                        # 첨가제 wt% 합계 상한
    allowed_names: dict = field(default_factory=dict)       # class -> [허용 이름]; 없으면 미검사
    incompatible: list = field(default_factory=list)        # [[이름, 이름], ...]


def load_rules(src):
    """dict 또는 JSON 파일 경로 -> Rules. '_'로 시작하는 키(설명)는 무시한다."""
    if isinstance(src, (str, bytes)) or hasattr(src, "__fspath__"):
        with open(src, encoding="utf-8") as f:
            src = json.load(f)
    return Rules(**{k: v for k, v in src.items() if not k.startswith("_")})


def validate(components, rules):
    """components: [{component_class, name, amount, unit, basis}] -> [(코드, 메시지)]. 비어 있으면 통과."""
    issues = []
    solvent_total = additive_total = 0.0
    names = set()
    has_solvent = False
    for c in components:
        cls, name, amt, unit = c["component_class"], c["name"], c["amount"], c["unit"]
        names.add(name)
        want = rules.unit_by_class.get(cls)
        if want is None:
            issues.append(("UNKNOWN_CLASS", f"{name}: 알 수 없는 성분 구분 '{cls}'"))
            continue
        if amt is None or amt < 0:
            issues.append(("NEGATIVE", f"{name}: 함량이 없거나 음수({amt})"))
            continue
        if unit != want:
            issues.append(("UNIT", f"{name}: {cls} 는 {want} 로 표기해야 한다(입력 {unit}). 자동 환산하지 않는다"))
        want_basis = rules.basis_by_class.get(cls)
        if want_basis and c.get("basis") != want_basis:
            issues.append(("BASIS", f"{name}: 기준 {want_basis} 필요(입력 {c.get('basis')})"))
        allowed = rules.allowed_names.get(cls)
        if allowed is not None and name not in allowed:
            issues.append(("NOT_ALLOWED", f"{name}: 허용 목록에 없는 {cls}"))
        rng = rules.ranges.get(f"{cls}::{name}")
        if rng and unit == want and not (rng[0] <= amt <= rng[1]):
            issues.append(("RANGE", f"{name}: {amt} {unit} 가 허용 범위 {rng[0]}~{rng[1]} 밖"))
        if cls == "solvent" and unit == want:
            solvent_total += amt
            has_solvent = True
        if cls == "additive" and unit == want:
            additive_total += amt
    if not has_solvent:
        issues.append(("NO_SOLVENT", "용매가 없다"))
    elif abs(solvent_total - rules.solvent_sum) > rules.solvent_tol:
        issues.append(("SOLVENT_SUM", f"용매 vol% 합계 {solvent_total:g} (기준 {rules.solvent_sum:g} ± {rules.solvent_tol:g})"))
    if rules.additive_total_max is not None and additive_total > rules.additive_total_max:
        issues.append(("ADDITIVE_TOTAL", f"첨가제 wt% 합계 {additive_total:g} > 상한 {rules.additive_total_max:g}"))
    for a, b in rules.incompatible:
        if a in names and b in names:
            issues.append(("INCOMPATIBLE", f"{a} 와 {b} 는 함께 쓸 수 없다"))
    return issues
