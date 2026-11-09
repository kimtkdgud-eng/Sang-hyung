"""지표 사전: 사내 지표 이름 -> 분류(상온수명/고온수명/고온저장) · 측정 방식(real/RPT/retention/recovery) · 양 · 필수 조건.

- real 과 RPT, retention 과 recovery 는 서로 다른 지표다. 이름이 다르면 합치지 않으며, 사전에 없는 이름은 '미분류'로 드러낸다.
- 필수 조건 키가 condition_json 에 없는 행은 비교 불가로 표시한다(값을 추정해 채우지 않는다).
- 사내 지표 이름·조건 키는 회사 값이다 -> configs/metric_registry.example.json 은 예시일 뿐이다.
- 가정: internal_results.temperature_C 는 사이클/저장 온도다. RPT 측정 온도는 rpt_temp_c 같은 조건 키로 따로 둔다.
"""
import json
from dataclasses import dataclass


@dataclass(frozen=True)
class MetricDef:
    category: str
    basis: str
    quantity: str
    required_conditions: tuple = ()

    @property
    def label(self):
        return f"{self.category}·{self.basis}·{self.quantity}"


def load_registry(src):
    if isinstance(src, (str, bytes)) or hasattr(src, "__fspath__"):
        with open(src, encoding="utf-8") as f:
            src = json.load(f)
    return {name: MetricDef(d["category"], d["basis"], d["quantity"], tuple(d.get("required_conditions", [])))
            for name, d in src["metrics"].items()}


def missing_conditions(definition, condition):
    have = {k for k, _ in condition}
    return [k for k in definition.required_conditions if k not in have]
