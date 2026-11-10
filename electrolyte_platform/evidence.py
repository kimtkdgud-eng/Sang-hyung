"""03 근거 패키지: 02 검증 결과를 해석 엔진(Research Reasoning Engine 등)에 넘기는 형식.

세 종류의 주장을 섞지 않는다.
  association              관찰된 상관(조건 내, 보정 없음)       -> 인과·기작 표현 금지
  predictive_contribution  사전 기준으로 비교한 추가 예측 기여     -> 결과·기준·표본·조건·한계를 반드시 포함
  mechanism_hypothesis     기작 가설(검증 전)                    -> 수치 근거를 달 수 없고 상태는 hypothesis_untested
모든 항목은 평가 조건, 표본 수, 출처, 한계를 가진다. 해석 엔진은 이 패키지를 근거로만 설명을 만들고, 한계 항목을 제거하지 않는다.
"""
from dataclasses import dataclass, field, asdict

KINDS = ("association", "predictive_contribution", "mechanism_hypothesis")
CAUSAL = ("인과", "원인이", "때문에", "유발", "causes", "caused by", "leads to", "proves", "입증", "증명")
SCHEMA_VERSION = "evidence-package/0.1"


@dataclass
class EvidenceItem:
    kind: str
    statement: str
    metric: str = ""
    unit: str = ""
    condition: str = ""
    n_compositions: int = 0
    n_batches: int = 0
    numbers: dict = field(default_factory=dict)
    source: str = ""                       # 계산·입력의 출처(예: addvalue 실행, 데이터 스냅샷 ID, 문헌 DOI)
    limits: list = field(default_factory=list)
    status: str = ""
    supports: list = field(default_factory=list)      # 가설이 참조하는 다른 항목의 인덱스(근거 연결)


def validate(item, index=None, n_items=None):
    errs = []
    if item.kind not in KINDS:
        return [f"알 수 없는 종류 {item.kind}"]
    if not item.statement.strip():
        errs.append("진술이 비어 있다")
    if not item.source.strip():
        errs.append("출처가 없다")
    if not item.limits:
        errs.append("한계(limits)가 없다")
    text = item.statement.lower()
    if item.kind in ("association", "predictive_contribution") and any(w in text for w in CAUSAL):
        errs.append("상관·예측 결과를 인과·기작으로 표현할 수 없다")
    if item.kind in ("association", "predictive_contribution"):
        if not item.condition or not item.metric:
            errs.append("지표와 평가 조건이 필요하다")
        if item.n_compositions <= 0:
            errs.append("표본(고유 조성 수)이 필요하다")
    if item.kind == "predictive_contribution":
        for k in ("mae_base", "mae_plus", "min_improvement", "ci_low", "ci_high", "split"):
            if k not in item.numbers:
                errs.append(f"예측 기여에는 {k} 가 필요하다")
        if not any("제조하지 않은" in l or "unmanufactured" in l for l in item.limits):
            errs.append("아직 제조하지 않은 후보에는 적용되지 않는다는 한계가 필요하다")
    if item.kind == "association" and not any("보정" in l or "confound" in l.lower() for l in item.limits):
        errs.append("상관에는 교란 미보정 한계가 필요하다")
    if item.kind == "mechanism_hypothesis":
        if item.numbers:
            errs.append("가설 항목에는 수치 근거를 직접 달 수 없다(supports 로 다른 항목을 참조)")
        if item.status != "hypothesis_untested":
            errs.append("가설의 상태는 hypothesis_untested 여야 한다")
        for i in item.supports:
            if not isinstance(i, int) or i < 0 or (n_items is not None and i >= n_items) or i == index:
                errs.append(f"supports 참조가 잘못됐다: {i}")
    return errs


def from_addvalue(result):
    """addvalue.compare 결과 -> EvidenceItem. 비교가 성립하지 않은 상태는 근거로 넘기지 않는다."""
    if result["status"] not in ("adopt_candidate", "keep_optional"):
        raise ValueError(f"비교가 완료되지 않은 결과({result['status']})는 근거가 될 수 없다")
    p = result["plan"]
    better = result["status"] == "adopt_candidate"
    scope = "조성 단위 교차검증" if p["split"] == "recipe" else "새 물질 제외 검증"
    u = result["unit"]
    if p["split"] == "material":
        helped = [b for b in result["by_material"] if b["helps"]]
        names = ", ".join(f"{b['material']} ({b['mean_improvement']:+.2f} {u})" for b in helped)
        outcome = (f"물성이 개선한 물질 {names}; 나머지 물질은 개선이 확인되지 않았다." if helped
                   else "어느 물질에서도 사전 기준을 만족하는 개선이 없었다.")
        statement = (f"{result['metric']} [{result['condition']}] 새 물질 제외 검증(물질별, 본페로니 보정 신뢰수준 "
                     f"{result['ci_level_adjusted']:.1%}): {outcome}")
    else:
        statement = (f"{result['metric']} [{result['condition']}] 에서 조성 단독 대비 조성+실측 물성의 MAE 차이는 "
                     f"{result['mean_improvement']:.3f} {u} ({p['ci_level']:.0%} 신뢰구간 {result['ci_low']:.3f}~{result['ci_high']:.3f}, {scope}) 이며 "
                     f"사전 기준(개선 ≥ {p['min_improvement']} {u} 이고 신뢰구간 하한 > 0)을 {'충족했다' if better else '충족하지 못했다'}.")
    return EvidenceItem(
        kind="predictive_contribution",
        statement=statement,
        metric=result["metric"], unit=result["unit"], condition=result["condition"],
        n_compositions=result["n_compositions"], n_batches=result["n_batches"],
        numbers=dict(mae_dummy=round(result["mae_dummy"], 4), mae_base=round(result["mae_base"], 4), mae_plus=round(result["mae_plus"], 4),
                     mean_improvement=round(result["mean_improvement"], 4), ci_low=round(result["ci_low"], 4),
                     ci_high=round(result["ci_high"], 4), ci_level=p["ci_level"], share_plus_better=round(result["share_plus_better"], 3),
                     min_improvement=p["min_improvement"], model=p["model"], split=p["split"],
                     n_tested_compositions=result["n_tested_compositions"], n_splits=p["n_splits"], n_repeats=p["n_repeats"], seed=p["seed"],
                     by_material=[{k: (round(v, 4) if isinstance(v, float) else v) for k, v in b.items()} for b in result["by_material"]]),
        source=f"electrolyte_platform.addvalue.compare (모델 {p['model']}, seed {p['seed']})",
        limits=[result["caveat"], f"{scope} 결과이며 전향적(prospective) 검증이 아니다. 신뢰구간은 조성을 독립 단위로 본 근사다.",
                "아직 제조하지 않은 후보에는 실측 물성 입력이 없어 같은 개선이 적용된다고 해석하지 않는다."],
        status="pre_registered_comparison")


def association_item(metric, unit, condition, n_compositions, n_batches, feature, rho, source, n_pairs=None):
    """외부 탐색 상관(예: Feature-to-Target v0.2 결과)을 같은 형식으로 담는다."""
    return EvidenceItem(
        kind="association", statement=f"{feature} 와 {metric} 사이에 조건 내 순위상관 rho={rho:+.2f} 이 관찰됐다.",
        metric=metric, unit=unit, condition=condition, n_compositions=n_compositions, n_batches=n_batches,
        numbers=dict(feature=feature, spearman_rho=rho, n_pairs=n_pairs), source=source,
        limits=["조건 내 탐색 상관이며 배치·교란·혼합물 닫힘 미보정이다.", "예측 기여나 기작의 증거가 아니다."], status="exploratory")


def hypothesis_item(statement, supports, source, limits=None):
    return EvidenceItem(kind="mechanism_hypothesis", statement=statement, source=source, supports=list(supports),
                        limits=limits or ["검증 전 가설이다. 실험적으로 판별하기 전에는 결론으로 쓰지 않는다."],
                        status="hypothesis_untested")


def package(items, question=""):
    """검증을 통과한 항목만 패키지로 만든다. 하나라도 위반이면 어떤 항목이 왜 안 되는지 알리고 만들지 않는다."""
    errors = {i: validate(it, i, len(items)) for i, it in enumerate(items)}
    errors = {i: e for i, e in errors.items() if e}
    if errors:
        raise ValueError("; ".join(f"[{i}] {', '.join(e)}" for i, e in errors.items()))
    counts = {k: sum(1 for it in items if it.kind == k) for k in KINDS}
    return dict(schema_version=SCHEMA_VERSION, question=question, counts=counts, items=[asdict(it) for it in items],
                handoff_notes=["해석은 이 항목들만 근거로 한다. limits 를 생략하거나 완화하지 않는다.",
                               "상관·예측 기여·기작 가설을 서로의 근거로 바꿔 쓰지 않는다.",
                               "연구자 검토 전 결론이 아니다."])


def to_markdown(pkg):
    lines = [f"### 근거 패키지 ({pkg['schema_version']})", "", f"질문: {pkg['question'] or '-'}", "",
             "| # | 종류 | 진술 | 표본(조성/배치) | 출처 |", "|---|---|---|---|---|"]
    for i, it in enumerate(pkg["items"]):
        lines.append(f"| {i} | {it['kind']} | {it['statement']} | {it['n_compositions']}/{it['n_batches']} | {it['source']} |")
    lines += ["", "**한계**"] + [f"- [{i}] {l}" for i, it in enumerate(pkg["items"]) for l in it["limits"]]
    return "\n".join(lines) + "\n"
