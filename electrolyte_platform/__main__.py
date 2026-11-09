"""사용:
  python -m electrolyte_platform coverage [--db 파일]
  python -m electrolyte_platform addvalue --metric "초기 DCIR" --unit mohm --min-improvement 0.5 [--condition-index N] [--db 파일]
--db 를 생략하면 가상 데이터로 실행한다.
"""
import argparse
from . import synthetic, coverage, addvalue
from .adapters import SqlAdapter
from .demo_schema import connect
from .gate import MixedConditionsError

p = argparse.ArgumentParser()
p.add_argument("cmd", choices=["coverage", "addvalue"])
p.add_argument("--db")
p.add_argument("--signal", default="none", choices=["none", "property"], help="가상 데이터 전용")
p.add_argument("--metric")
p.add_argument("--unit")
p.add_argument("--min-improvement", type=float, help="결과를 보기 전에 정한 MAE 개선 최소폭(필수)")
p.add_argument("--condition-index", type=int, help="coverage 표에서 해당 지표의 조건 순번(0부터)")
p.add_argument("--model", default="random_forest")
a = p.parse_args()
con = connect(a.db) if a.db else synthetic.build(signal=a.signal)
ad = SqlAdapter(con)
if a.cmd == "coverage":
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
