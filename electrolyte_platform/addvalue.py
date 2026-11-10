"""조성 단독 vs 조성+실측 물성: 추가 예측 기여 비교.

원칙 (로드맵 §3):
  - 같은 표본·같은 모델·같은 분할에서 비교한다. 표본은 지표 1개 x 동일 평가 조건 1개.
  - 표본 단위 = 제조 배치(반복 셀은 평균). 검증 그룹 = 조성(recipe): 같은 조성의 배치·반복 셀이 학습과 평가에 동시에 들어가지 않는다.
  - 물성 누락·비교 불가 배치는 제외한다(0으로 채우지 않는다). 조성 성분이 없는 것은 실제로 양이 0이다.
  - 개선의 실무 기준(Plan)은 결과를 보기 전에 정한다. min_improvement 는 필수 인자다.
  - 판정: 개선 평균이 min_improvement 이상이고, 조성 단위 짝지은 부트스트랩 신뢰구간의 하한이 0보다 클 때만 채택 후보.
    (같은 데이터를 여러 번 섞은 분할 비율은 독립 근거가 아니므로 판정에 쓰지 않는다. 참고로 조성별 개선 비율만 보고한다.)
  - split='material': 특정 물질이 든 조성을 통째로 평가에 쓰고 학습에서는 뺀다(새 물질 일반화 진단).
    조성 이름만으로는 새 물질을 일반화할 수 없지만 물성은 도움이 될 수 있다. 물성이 도움이 되는 물질은 일부일 수 있으므로
    **물질별로** 판정하고(평균 내지 않는다), 물질 수만큼 신뢰수준을 본페로니로 보정한다. 조성들이 물질을 공유하므로 신뢰구간은 낙관적일 수 있다.
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
    min_compositions: int = 20
    n_splits: int = 5
    n_repeats: int = 10
    seed: int = 0
    model: str = "random_forest"     # 'random_forest' | 'ridge'
    split: str = "recipe"            # 'recipe' | 'material'
    ci_level: float = 0.95
    n_boot: int = 2000
    min_holdout_recipes: int = 5     # split='material': 빼는 물질이 든 조성 최소 수
    min_train_recipes: int = 10      # split='material': 그 물질이 없는 학습 조성 최소 수


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


def paired_bootstrap_ci(diffs, level=0.95, n_boot=2000, seed=0):
    """조성별 오차 차이의 평균에 대한 부트스트랩 신뢰구간(조성이 분석 단위)."""
    import numpy as np
    d = np.asarray(diffs, dtype=float)
    idx = np.random.default_rng(seed).integers(0, len(d), size=(n_boot, len(d)))
    means = d[idx].mean(axis=1)
    a = (1 - level) / 2
    return float(np.quantile(means, a)), float(np.quantile(means, 1 - a))


def material_holdouts(samples, min_holdout=5, min_train=10):
    """물질별로 (물질, 학습 인덱스, 평가 인덱스). 평가 = 그 물질이 든 조성 전체, 학습 = 그 물질이 없는 조성."""
    has = defaultdict(set)
    for s in samples:
        for k, v in s["comp"].items():
            if v and v > 0:
                has[k.split("::")[2]].add(s["recipe_id"])
    all_r = {s["recipe_id"] for s in samples}
    out = []
    for m, rs in sorted(has.items()):
        if len(rs) >= min_holdout and len(all_r) - len(rs) >= min_train:
            out.append((m, [i for i, s in enumerate(samples) if s["recipe_id"] not in rs],
                        [i for i, s in enumerate(samples) if s["recipe_id"] in rs]))
    return out


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
    if plan.split not in ("recipe", "material"):
        raise ValueError("split 은 'recipe' 또는 'material'")
    Xb, _ = _matrix(samples, False, cfg)
    Xp, _ = _matrix(samples, True, cfg)
    y = np.array([s["y"] for s in samples])
    rid = np.array([s["recipe_id"] for s in samples])
    model = _make_model(plan)
    n = len(y)
    eb, ep, ed = [[] for _ in range(n)], [[] for _ in range(n)], [[] for _ in range(n)]

    def fit_eval(tr, te):
        mb = clone(model).fit(Xb[tr], y[tr]); mp = clone(model).fit(Xp[tr], y[tr])
        pb, pp, pd = mb.predict(Xb[te]), mp.predict(Xp[te]), y[tr].mean()
        for k, i in enumerate(te):
            eb[i].append(abs(pb[k] - y[i])); ep[i].append(abs(pp[k] - y[i])); ed[i].append(abs(pd - y[i]))

    repeats, by_material = [], []
    if plan.split == "recipe":
        for rep in range(plan.n_repeats):
            order = list(recipes)
            random.Random(plan.seed * 1000 + rep).shuffle(order)
            fold_of = {r: i % plan.n_splits for i, r in enumerate(order)}
            fold = np.array([fold_of[r] for r in rid])
            for f in range(plan.n_splits):
                fit_eval(np.where(fold != f)[0], np.where(fold == f)[0])
            last = lambda arr: np.array([x[-1] for x in arr])
            repeats.append(dict(repeat=rep, mae_base=float(last(eb).mean()), mae_plus=float(last(ep).mean()),
                                mae_dummy=float(last(ed).mean())))
    else:
        holds = material_holdouts(samples, plan.min_holdout_recipes, plan.min_train_recipes)
        if not holds:
            result.update(status="insufficient", decision=(
                f"새 물질 제외 분할이 가능한 물질이 없다(빼는 물질이 든 조성 ≥ {plan.min_holdout_recipes}개이고 "
                f"없는 조성 ≥ {plan.min_train_recipes}개 필요). 조성 분할(split='recipe')을 쓰거나 데이터를 보강한다."))
            return result
        level_adj = 1 - (1 - plan.ci_level) / len(holds)          # 본페로니: 물질 수만큼 보정
        result["ci_level_adjusted"] = level_adj
        for m, tr, te in holds:
            tr, te = np.array(tr), np.array(te)
            fit_eval(tr, te)
            by_rec = defaultdict(list)
            for i in te:
                by_rec[rid[i]].append(eb[i][-1] - ep[i][-1])
            d = [float(np.mean(v)) for v in by_rec.values()]
            lo_m, hi_m = paired_bootstrap_ci(d, level_adj, plan.n_boot, plan.seed)
            mi = float(np.mean(d))
            by_material.append(dict(material=m, n_test_recipes=len(by_rec), n_train_recipes=len({rid[i] for i in tr}),
                                    mae_base=float(np.mean([eb[i][-1] for i in te])), mae_plus=float(np.mean([ep[i][-1] for i in te])),
                                    mean_improvement=mi, ci_low=lo_m, ci_high=hi_m,
                                    helps=bool(mi >= plan.min_improvement and lo_m > 0)))
    tested = [i for i in range(n) if eb[i]]
    mb_, mp_, md_ = (np.array([np.mean(a[i]) for i in tested]) for a in (eb, ep, ed))
    per_recipe = defaultdict(list)
    for k, i in enumerate(tested):
        per_recipe[rid[i]].append(mb_[k] - mp_[k])
    diffs = [float(np.mean(v)) for v in per_recipe.values()]            # 양수 = 물성 포함이 더 좋음
    lo, hi = paired_bootstrap_ci(diffs, plan.ci_level, plan.n_boot, plan.seed)
    mean_diff = float(np.mean(diffs))
    result.update(repeats=repeats, by_material=by_material, n_tested_compositions=len(diffs),
                  mae_dummy=float(md_.mean()), mae_base=float(mb_.mean()), mae_plus=float(mp_.mean()),
                  mean_improvement=mean_diff, ci_low=lo, ci_high=hi,
                  share_plus_better=float(np.mean([d > 0 for d in diffs])))
    scope = "같은 조성 분할" if plan.split == "recipe" else "새 물질 제외 분할"
    if plan.split == "material":
        helpers = [b["material"] for b in by_material if b["helps"]]
        if helpers:
            result.update(status="adopt_candidate", decision=(
                f"[{scope}] 물성이 새 물질 예측을 사전 기준 이상으로 개선한 물질: {', '.join(helpers)} (보정된 신뢰수준 {result['ci_level_adjusted']:.1%}). "
                "나머지 물질에서는 개선이 확인되지 않았다. 물성이 기여한 경로를 확인한 뒤 후속 실험·DOE 반영을 검토한다."))
        else:
            result.update(status="keep_optional", decision=(
                f"[{scope}] 어느 물질에서도 사전 기준과 보정된 신뢰구간을 동시에 만족하는 개선이 없다. 물성 입력은 선택 기능으로 유지한다."))
    elif mean_diff >= plan.min_improvement and lo > 0:
        result.update(status="adopt_candidate", decision=(
            f"[{scope}] 물성 추가 개선이 사전 기준을 넘고 신뢰구간이 0 위에 있다. 어떤 물성이 기여했는지(하나씩 제거 비교) 확인한 뒤 "
            "후속 실험·DOE 반영을 검토한다."))
    else:
        result.update(status="keep_optional", decision=(
            f"[{scope}] 개선이 사전 기준에 못 미치거나 0과 구분되지 않는다. 물성 입력은 선택 기능으로 유지한다."))
    return result


def to_markdown(r):
    u = r["unit"]
    pl = r["plan"]
    scope = "조성 단위 5-fold 반복" if pl["split"] == "recipe" else "새 물질 제외(물질별 hold-out)"
    lines = [f"### 조성 단독 vs 조성+실측 물성 — {r['metric']} ({u}) [{r['condition']}]", "",
             f"- 표본: 고유 조성 {r['n_compositions']}개 · 배치 {r['n_batches']}개 · 셀 결과 {r['n_cells']}행",
             f"- 제외: {', '.join(f'{k} {v}' for k, v in sorted(r['excluded'].items())) or '-'}",
             f"- 분할: {scope} · 모델 {pl['model']} · seed {pl['seed']}",
             f"- 사전 기준: MAE 개선 ≥ {pl['min_improvement']} {u} **그리고** {pl['ci_level']:.0%} 신뢰구간 하한 > 0 (조성 단위 짝지은 부트스트랩)", ""]
    if r["status"] in ("insufficient", "blocked_incomplete_conditions"):
        return "\n".join(lines + [f"**결정:** {r['decision']}", "", r["caveat"], ""])
    lines += ["| 모델 | 검증 MAE (" + u + ") |", "|---|---|",
              f"| 평균값 예측(참고) | {r['mae_dummy']:.3f} |", f"| 조성 단독 | {r['mae_base']:.3f} |",
              f"| 조성+실측 물성 | {r['mae_plus']:.3f} |", "",
              f"- MAE 개선(조성 단독 − 조성+물성): **{r['mean_improvement']:.3f} {u}**, {pl['ci_level']:.0%} 신뢰구간 [{r['ci_low']:.3f}, {r['ci_high']:.3f}] (조성 {r['n_tested_compositions']}개)",
              f"- 물성 포함이 더 나았던 조성 비율 {r['share_plus_better']:.0%} (참고용)"]
    if r["by_material"]:
        lines += ["", f"물질별 판정(보정된 신뢰수준 {r['ci_level_adjusted']:.1%}; 위 평균은 물질을 섞은 참고값이며 판정에 쓰지 않는다)", "",
                  "| 뺀 물질 | 평가 조성 | 학습 조성 | 조성 단독 MAE | 조성+물성 MAE | 개선 [신뢰구간] | 기준 충족 |", "|---|---|---|---|---|---|---|"]
        lines += [f"| {b['material']} | {b['n_test_recipes']} | {b['n_train_recipes']} | {b['mae_base']:.3f} | {b['mae_plus']:.3f} | "
                  f"{b['mean_improvement']:+.3f} [{b['ci_low']:.3f}, {b['ci_high']:.3f}] | {'예' if b['helps'] else '아니오'} |" for b in r["by_material"]]
        lines += ["", "조성들이 물질을 공유하므로 신뢰구간은 낙관적일 수 있다."]
    return "\n".join(lines + ["", f"**결정:** {r['decision']}", "", r["caveat"], ""])
