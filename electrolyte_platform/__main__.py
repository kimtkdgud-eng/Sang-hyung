"""사용:
  python -m electrolyte_platform coverage|hub [--rules 규칙.json] [--db 파일]
  python -m electrolyte_platform screen --candidates 후보.json [--rules 규칙.json]
  python -m electrolyte_platform addvalue --metric "초기 DCIR" --unit mohm --min-improvement 0.5 [--condition-index N] [--db 파일]
--db 를 생략하면 가상 데이터로 실행한다.
"""
import argparse
import json
from . import synthetic, coverage, addvalue, hub_contract, doe_constraints
from .composition import load_rules, Rules
from .adapters import SqlAdapter
from .demo_schema import connect
from .gate import MixedConditionsError

p = argparse.ArgumentParser()
p.add_argument("cmd", choices=["coverage", "addvalue", "hub", "screen"])
p.add_argument("--db")
p.add_argument("--signal", default="none", choices=["none", "property"], help="가상 데이터 전용")
p.add_argument("--metric")
p.add_argument("--unit")
p.add_argument("--min-improvement", type=float, help="결과를 보기 전에 정한 MAE 개선 최소폭(필수)")
p.add_argument("--condition-index", type=int, help="coverage 표에서 해당 지표의 조건 순번(0부터)")
p.add_argument("--model", default="random_forest")
p.add_argument("--rules", help="조성 규칙 JSON (예: configs/composition_rules.example.json)")
p.add_argument("--candidates", help="screen: 후보 JSON [{id, components:[...]}]")
a = p.parse_args()
con = connect(a.db) if a.db else synthetic.build(signal=a.signal)
ad = SqlAdapter(con)
rules = load_rules(a.rules) if a.rules else Rules()
if a.cmd == "hub":
    print(hub_contract.to_markdown(hub_contract.check(ad, rules)))
elif a.cmd == "screen":
    if not a.candidates:
        p.error("screen 에는 --candidates 가 필요하다")
    print(doe_constraints.to_markdown(doe_constraints.screen(json.load(open(a.candidates, encoding="utf-8")), rules)))
elif a.cmd == "coverage":
    print(coverage.to_markdown(coverage.build_table(ad)))
else:
    if not (a.metric and a.unit and a.min_improvement is not None):
        p.error("addvalue 에는 --metric --unit --min-improvement 가 필요하다")
    key = None
    if a.condition_index is not None:
        keys = [t["key"] for t in coverage.build_table(ad) if t["metric"] == a.metric and t["unit"] == a.unit]
        key = keys[a.condition_index]
    try:
        print(addvalue.to_markdown(addvalue.compare(ad, a.metric, a.unit, addvalue.Plan(a.min_improvement, model=a.model), key)))
    except MixedConditionsError as e:
        print(f"차단: {e}")
