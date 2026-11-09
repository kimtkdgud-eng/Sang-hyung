"""조성 단독 vs 조성+실측 물성: 추가 예측 기여 비교.

원칙 (로드맵 §3):
  - 같은 표본·같은 모델·같은 분할에서 비교한다. 표본은 지표 1개 x 동일 평가 조건 1개.
  - 표본 단위 = 제조 배치(반복 셀은 평균). 검증 그룹 = 조성(recipe): 같은 조성의 배치·반복 셀이 학습과 평가에 동시에 들어가지 않는다.
  - 물성 누락·비교 불가 배치는 제외한다(0으로 채우지 않는다). 조성 성분이 없는 것은 실제로 양이 0이다.
  - 개선의 실무 기준(Plan)은 결과를 보기 전에 정한다. min_improvement 는 필수 인자다.
  - 실측 물성을 쓴 성과는 아직 제조하지 않은 후보에는 적용되지 않는다(물성을 먼저 측정해야 하므로).
"""
import random
import statistics
from collections import defaultdict
from dataclasses import dataclass, asdict

from .coverage import Config, classify, props_by_batch, condition_label
from .gate import select_group
from .registry import missing_conditions


@dataclass(frozen=True)
class Plan:
    min_improvement: float           # 지표 원래 단위의 MAE 개선 최소폭 (결과를 보기 전에 정한다)
    min_consistency: float = 0.8     # 반복 분할 중 물성 포함 모델이 더 나은 비율의 최소값
    min_compositions: int = 20
    n_splits: int = 5
    n_repeats: int = 10
    seed: int = 0
    model: str = "random_forest"     # 'random_forest' | 'ridge'


CAVEAT = ("이 결과는 물성이 실측된 배치에서의 비교다. 아직 제조·측정하지 않은 후보에는 물성 입력이 없으므로 "
          "같은 개선이 적용된다고 해석하지 않는다. 합성 데이터 결과는 구조 확인용이다.")


def _make_model(plan):
    from sklearn.ensemble import RandomForestRegressor
    from sklearn.linear_model import Ridge
    from sklearn.pipeline import make_pipeline
    from sklearn.preprocessing import StandardScaler
    if plan.model == "random_forest":
        return RandomForestRegressor(n_estimators=200, random_state=plan.seed, n_jobs=1)
    if plan.model == "ridge":
        return make_pipeline(StandardScaler(), Ridge(alpha=1.0))
    raise ValueError(f"알 수 없는 모델: {plan.model}")


def build_samples(adapter, metric, unit, condition_key=None, cfg=None, require_props=True):
    """-> (samples, condition_key, 요약). sample: batch_id, recipe_id, y, n_cells, comp(dict), props(dict)."""
    cfg = cfg or Config()
    rows, key = select_group(adapter.results(), metric, unit, condition_key)
    batch_recipe = adapter.batch_recipe()
    meas = props_by_batch(adapter)
    comps = adapter.components()
    per_batch = defaultdict(list)
    skipped = defaultdict(int)
    for r in rows:
        if r.batch_id is None:
            skipped["배치 ID 누락(셀 결과)"] += 1
        elif r.batch_id not in batch_recipe:
            skipped["배치 ID 미등록(셀 결과)"] += 1
        elif r.value is None:
            skipped["셀 결과값 없음"] += 1
        else:
            per_batch[r.batch_id].append(r.value)
    samples = []
    for b, ys in per_batch.items():
        props, ok = {}, True
        for p in (cfg.required_props if require_props else ()):
            su, st = cfg.standard[p]
            usable, why, _ = classify(meas[b].get(p, []), su, st)
            if not usable:
                skipped[f"{p} 사용 불가"] += 1        # 배치 단위로 센다
                ok = False
                continue
            vals = [m.value for m in meas[b][p] if m.unit == su and m.temp_c == st and m.value is not None]
            props[p] = statistics.fmean(vals)           # 중복 측정은 평균(원본은 DB에 그대로 남는다)
        rid = batch_recipe[b]
        if ok and comps.get(rid):
            samples.append(dict(batch_id=b, recipe_id=rid, y=statistics.fmean(ys), n_cells=len(ys),
                                comp={f"cmp::{c['component_class']}::{c['name']}::{c['unit']}::{c['basis']}": c["amount"]
                                      for c in comps[rid]}, props=props))
        elif ok:
            skipped["조성 성분 없음"] += 1
    return samples, key, dict(skipped)


def _matrix(samples, with_props, cfg):
    import numpy as np
    comp_names = sorted({k for s in samples for k in s["comp"]})
    names = comp_names + ([f"prop::{p}" for p in cfg.required_props] if with_props else [])
    X = np.array([[s["comp"].get(k, 0.0) for k in comp_names] +
                  ([s["props"][p] for p in cfg.required_props] if with_props else []) for s in samples], dtype=float)
    return X, names


def compare(adapter, metric, unit, plan, condition_key=None, cfg=None, registry=None):
    import numpy as np
    from sklearn.base import clone
    cfg = cfg or Config()
    samples, key, skipped = build_samples(adapter, metric, unit, condition_key, cfg)
    recipes = sorted({s["recipe_id"] for s in samples})
    miss = missing_conditions(registry.get(metric), key[3]) if registry and registry.get(metric) else []
    result = dict(metric=metric, unit=unit, condition=condition_label(key), plan=asdict(plan),
                  n_compositions=len(recipes), n_batches=len(samples), n_cells=sum(s["n_cells"] for s in samples),
                  excluded=skipped, caveat=CAVEAT)
    if miss:
        result.update(status="blocked_incomplete_conditions",
                      decision=f"필수 평가 조건이 기재되지 않아 비교할 수 없다: {', '.join(miss)}. 조건을 보완한 뒤 다시 실행한다.")
        return result
    if len(recipes) < max(plan.min_compositions, plan.n_splits):
        result.update(status="insufficient",
                      decision=(f"비교 표본이 부족하다(고유 조성 {len(recipes)}개 < 기준 {plan.min_compositions}개). "
                                "다음 모델 개발보다 부족한 배치 매핑·물성 측정을 먼저 보강한다."))
        return result
    Xb, _ = _matrix(samples, False, cfg)
    Xp, _ = _matrix(samples, True, cfg)
    y = np.array([s["y"] for s in samples])
    rid = np.array([s["recipe_id"] for s in samples])
    model = _make_model(plan)
    repeats = []
    for rep in range(plan.n_repeats):
        order = list(recipes)
        random.Random(plan.seed * 1000 + rep).shuffle(order)
        fold_of = {r: i % plan.n_splits for i, r in enumerate(order)}
        fold = np.array([fold_of[r] for r in rid])
        pb, pp, pd = np.zeros(len(y)), np.zeros(len(y)), np.zeros(len(y))
        folds = []
        for f in range(plan.n_splits):
            te, tr = fold == f, fold != f
            mb = clone(model).fit(Xb[tr], y[tr])
            mp = clone(model).fit(Xp[tr], y[tr])
            pb[te], pp[te], pd[te] = mb.predict(Xb[te]), mp.predict(Xp[te]), y[tr].mean()
            folds.append(dict(fold=f, n_test=int(te.sum()),
                              mae_base=float(np.abs(pb[te] - y[te]).mean()), mae_plus=float(np.abs(pp[te] - y[te]).mean())))
        repeats.append(dict(repeat=rep, mae_dummy=float(np.abs(pd - y).mean()), mae_base=float(np.abs(pb - y).mean()),
                            mae_plus=float(np.abs(pp - y).mean()), folds=folds))
    diffs = [r["mae_base"] - r["mae_plus"] for r in repeats]          # 양수 = 물성 포함이 더 좋음
    better = sum(d > 0 for d in diffs) / len(diffs)
    mean_diff = statistics.fmean(diffs)
    result.update(repeats=repeats, mae_dummy=statistics.fmean(r["mae_dummy"] for r in repeats),
                  mae_base=statistics.fmean(r["mae_base"] for r in repeats),
                  mae_plus=statistics.fmean(r["mae_plus"] for r in repeats),
                  mean_improvement=mean_diff, share_plus_better=better)
    if mean_diff >= plan.min_improvement and better >= plan.min_consistency:
        result.update(status="adopt_candidate", decision=(
            "물성 추가 개선이 사전 기준을 넘고 일관되다. 어떤 물성이 기여했는지(하나씩 제거 비교) 확인한 뒤 후속 실험·DOE 반영을 검토한다."))
    else:
        result.update(status="keep_optional", decision=(
            "개선이 사전 기준에 못 미치거나 분할마다 불안정하다. 물성 입력은 선택 기능으로 유지한다."))
    return result


def to_markdown(r):
    u = r["unit"]
    lines = [f"### 조성 단독 vs 조성+실측 물성 — {r['metric']} ({u}) [{r['condition']}]", "",
             f"- 표본: 고유 조성 {r['n_compositions']}개 · 배치 {r['n_batches']}개 · 셀 결과 {r['n_cells']}행",
             f"- 제외: {', '.join(f'{k} {v}' for k, v in sorted(r['excluded'].items())) or '-'}",
             f"- 사전 기준: MAE 개선 ≥ {r['plan']['min_improvement']} {u}, 반복 분할 중 {r['plan']['min_consistency']:.0%} 이상에서 개선 "
             f"(모델 {r['plan']['model']}, {r['plan']['n_splits']}-fold x {r['plan']['n_repeats']}회, seed {r['plan']['seed']})", ""]
    if r["status"] in ("insufficient", "blocked_incomplete_conditions"):
        return "\n".join(lines + [f"**결정:** {r['decision']}", "", r["caveat"], ""])
    lines += ["| 모델 | 검증 MAE (" + u + ") |", "|---|---|",
              f"| 평균값 예측(참고) | {r['mae_dummy']:.3f} |", f"| 조성 단독 | {r['mae_base']:.3f} |",
              f"| 조성+실측 물성 | {r['mae_plus']:.3f} |", "",
              f"- MAE 개선(조성 단독 − 조성+물성): **{r['mean_improvement']:.3f} {u}**, 물성 포함이 더 나았던 분할 비율 {r['share_plus_better']:.0%}",
              f"- 반복별 개선: " + ", ".join(f"{r_['mae_base'] - r_['mae_plus']:+.2f}" for r_ in r["repeats"]), "",
              f"**결정:** {r['decision']}", "", r["caveat"], ""]
    return "\n".join(lines)
