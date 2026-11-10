"""사용:
  python -m electrolyte_platform preflight|coverage|hub [--rules 규칙.json] [--db 파일 --sql 사내SELECT.json]
  python -m electrolyte_platform screen --candidates 후보.json [--rules 규칙.json]
  python -m electrolyte_platform doe --objective "지표|%|max" --space 공간.json --rules 규칙.json
  python -m electrolyte_platform addvalue --metric "상온수명/real/용량유지율" --unit % --min-improvement 0.5 [--condition-index N] [--db 파일]
--db 를 생략하면 가상 데이터로 실행한다.
"""
import argparse
import json
from . import synthetic, coverage, addvalue, hub_contract, doe_constraints
from .registry import load_registry
from .composition import load_rules, Rules
from .adapters import SqlAdapter, open_readonly, preflight, preflight_markdown
from .gate import MixedConditionsError

p = argparse.ArgumentParser()
p.add_argument("cmd", choices=["preflight", "coverage", "addvalue", "hub", "screen", "doe"])
p.add_argument("--db", help="사내 SQLite 파일(읽기 전용으로 열린다). 생략하면 가상 데이터")
p.add_argument("--sql", help="사내 테이블에 맞춘 SELECT JSON ({results,batches,properties,components,versions,qc})")
p.add_argument("--signal", default="none", choices=["none", "property", "mediated"], help="가상 데이터 전용")
p.add_argument("--metric")
p.add_argument("--unit")
p.add_argument("--min-improvement", type=float, help="결과를 보기 전에 정한 MAE 개선 최소폭(필수)")
p.add_argument("--condition-index", type=int, help="coverage 표에서 해당 지표의 조건 순번(0부터)")
p.add_argument("--model", default="random_forest")
p.add_argument("--split", default="recipe", choices=["recipe", "material"], help="addvalue: 조성 분할 또는 새 물질 제외 분할")
p.add_argument("--registry", help="지표 사전 JSON (예: configs/metric_registry.example.json)")
p.add_argument("--objective", action="append", help="doe: '지표|단위|max또는min' (여러 번 지정 가능)")
p.add_argument("--space", help="doe: 탐색 공간 JSON (예: configs/doe_space.example.json)")
p.add_argument("--rules", help="조성 규칙 JSON (예: configs/composition_rules.example.json)")
p.add_argument("--candidates", help="screen: 후보 JSON [{id, components:[...]}]")
a = p.parse_args()
con = open_readonly(a.db) if a.db else synthetic.build(signal=a.signal)
sql = {k: v for k, v in json.load(open(a.sql, encoding="utf-8")).items() if not k.startswith("_")} if a.sql else None
ad = SqlAdapter(con, sql)
rules = load_rules(a.rules) if a.rules else Rules()
reg = load_registry(a.registry) if a.registry else None
if a.cmd == "preflight":
    print(preflight_markdown(preflight(ad)))
elif a.cmd == "hub":
    print(hub_contract.to_markdown(hub_contract.check(ad, rules)))
elif a.cmd == "doe":
    if not (a.objective and a.space and a.rules):
        p.error("doe 에는 --objective --space --rules 가 필요하다")
    from . import doe_pipeline as dp
    sp = {k: v for k, v in json.load(open(a.space, encoding="utf-8")).items() if not k.startswith("_")}
    objs = [dp.Objective(*o.split("|")) for o in a.objective]
    try:
        print(dp.to_markdown(dp.run(ad, objs, dp.Space(**sp), rules)))
    except MixedConditionsError as e:
        print(f"차단: {e}")
elif a.cmd == "screen":
    if not a.candidates:
        p.error("screen 에는 --candidates 가 필요하다")
    print(doe_constraints.to_markdown(doe_constraints.screen(json.load(open(a.candidates, encoding="utf-8")), rules)))
elif a.cmd == "coverage":
    print(coverage.to_markdown(coverage.build_table(ad, registry=reg)))
else:
    if not (a.metric and a.unit and a.min_improvement is not None):
        p.error("addvalue 에는 --metric --unit --min-improvement 가 필요하다")
    key = None
    if a.condition_index is not None:
        keys = [t["key"] for t in coverage.build_table(ad, registry=reg) if t["metric"] == a.metric and t["unit"] == a.unit]
        key = keys[a.condition_index]
    try:
        print(addvalue.to_markdown(addvalue.compare(ad, a.metric, a.unit, addvalue.Plan(a.min_improvement, model=a.model, split=a.split), key, registry=reg)))
    except MixedConditionsError as e:
        print(f"차단: {e}")
