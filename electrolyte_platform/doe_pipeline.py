"""04 DOE 파이프라인: 후보 생성 -> 예측(+불확실도·외삽 위험) -> 조성 규칙 검토 -> Pareto -> 연구자 승인 대기.

- 아직 제조하지 않은 후보에는 실측 물성이 없으므로 예측은 **조성 단독** 모델이다(물성 추가 기여 결과를 쓰지 않는다).
- 예측은 의사결정 지원이며 검증이 아니다. 학습 조성에서 먼 후보·학습에 없는 성분은 외삽 위험으로 표시한다.
- 통과 후보도 자동 승인하지 않는다. 승인·반려·보류는 DecisionLog 에 추가(append)로만 기록한다.
- 예측기는 교체 가능하다(predict 인터페이스). 본체 v2.12 모델을 붙일 때는 같은 인터페이스의 Adapter 를 만든다.
"""
import random
import sqlite3
import statistics
import time
from dataclasses import dataclass, field

from .addvalue import build_samples
from .composition import Rules
from .coverage import Config
from .doe_constraints import screen

CAVEAT = ("조성 단독 예측이며 실측·검증이 아니다. 외삽 위험이 높은 후보는 특히 주의한다. "
          "모든 후보는 연구자 승인 전에는 실험 대상이 아니다.")


@dataclass(frozen=True)
class Objective:
    metric: str
    unit: str
    direction: str                  # 'max' | 'min'
    condition_key: tuple = None     # 조건이 여럿이면 선택(gate 와 동일)


@dataclass
class Space:
    salts: dict                     # 이름 -> [최소, 최대] mol/L
    solvents: list                  # 이름 목록 (vol%, 합계 100)
    additives: dict = field(default_factory=dict)   # 이름 -> [최소, 최대] wt%
    solvent_step: float = 5.0
    max_additives: int = 2


@dataclass(frozen=True)
class DoePlan:
    n_candidates: int = 500
    top_k: int = 10
    seed: int = 0
    min_compositions: int = 20
    risk_threshold: float = 1.5     # 학습 조성 간 최근접 거리의 90백분위 대비 배수


def _basis(rules):
    return rules.basis_by_class.get("additive", "total_electrolyte")


def generate(space, rules, n, seed=0):
    rnd = random.Random(seed)
    units = int(round(100 / space.solvent_step))
    out = []
    for i in range(n):
        k = rnd.randint(min(2, len(space.solvents)), len(space.solvents))
        chosen = rnd.sample(space.solvents, k)
        cuts = sorted(rnd.sample(range(1, units), k - 1)) if k > 1 else []
        parts = [b - a for a, b in zip([0] + cuts, cuts + [units])]
        comps = []
        name = rnd.choice(sorted(space.salts))
        lo, hi = space.salts[name]
        comps.append(dict(component_class="salt", name=name, amount=round(rnd.uniform(lo, hi), 2), unit="mol/L", basis="total_electrolyte"))
        for n_, u in zip(chosen, parts):
            comps.append(dict(component_class="solvent", name=n_, amount=u * space.solvent_step, unit="vol%", basis="total_electrolyte"))
        add_names = rnd.sample(sorted(space.additives), rnd.randint(0, min(space.max_additives, len(space.additives))))
        for a in add_names:
            lo, hi = space.additives[a]
            comps.append(dict(component_class="additive", name=a, amount=round(rnd.uniform(lo, hi), 2), unit="wt%", basis=_basis(rules)))
        out.append({"id": f"CAND-{seed}-{i:04d}", "components": comps})
    return out


def _key(c):
    return f"cmp::{c['component_class']}::{c['name']}::{c['unit']}::{c['basis']}"


class CompositionModel:
    """조성 단독 랜덤 포레스트 + 불확실도(트리 간 표준편차) + 외삽 위험(최근접 학습 조성까지의 표준화 거리)."""

    def __init__(self, adapter, objective, cfg=None, seed=0):
        import numpy as np
        from sklearn.ensemble import RandomForestRegressor
        self.np, self.obj = np, objective
        samples, self.condition_key, self.skipped = build_samples(
            adapter, objective.metric, objective.unit, objective.condition_key, cfg or Config(), require_props=False)
        self.n_compositions = len({s["recipe_id"] for s in samples})
        self.names = sorted({k for s in samples for k in s["comp"]})
        self.ok = bool(samples)
        if not samples:
            return
        X = self._x([s["comp"] for s in samples])
        self.y = np.array([s["y"] for s in samples])
        self.mu, self.sd = X.mean(0), X.std(0)
        self.sd[self.sd == 0] = 1.0
        self.Z = (X - self.mu) / self.sd
        self.rf = RandomForestRegressor(n_estimators=200, random_state=seed, n_jobs=1).fit(X, self.y)
        d = []
        for i in range(len(self.Z)):
            dist = np.linalg.norm(self.Z - self.Z[i], axis=1)
            dist = dist[(dist > 1e-12)]
            if len(dist):
                d.append(dist.min())
        self.ref = float(np.percentile(d, 90)) if d else 1.0

    def _x(self, comps_list):
        return self.np.array([[c.get(k, 0.0) for k in self.names] for c in comps_list], dtype=float)

    def predict(self, candidates):
        np = self.np
        comps = [{_key(c): c["amount"] for c in cand["components"]} for cand in candidates]
        X = self._x(comps)
        tree = np.array([t.predict(X) for t in self.rf.estimators_])
        mean, std = tree.mean(0), tree.std(0)
        Z = (X - self.mu) / self.sd
        out = []
        for i, cd in enumerate(comps):
            dist = float(np.linalg.norm(self.Z - Z[i], axis=1).min())
            unseen = sorted(k for k in cd if k not in self.names)
            out.append(dict(mean=float(mean[i]), std=float(std[i]), nn_ratio=dist / self.ref, unseen=unseen))
        return out


def pareto_ranks(points, directions):
    """points: [[값,...]]; directions: ['max'|'min',...] -> 순위(1 = 비지배). 반복 비지배 정렬."""
    pts = [[-v if d == "max" else v for v, d in zip(p, directions)] for p in points]
    rank, remaining, r = {}, set(range(len(pts))), 1
    while remaining:
        front = [i for i in remaining
                 if not any(all(a <= b for a, b in zip(pts[j], pts[i])) and pts[j] != pts[i] for j in remaining if j != i)]
        for i in front:
            rank[i] = r
        remaining -= set(front)
        r += 1
    return [rank[i] for i in range(len(pts))]


def run(adapter, objectives, space, rules, plan=None, cfg=None):
    plan = plan or DoePlan()
    models = [CompositionModel(adapter, o, cfg, plan.seed) for o in objectives]
    short = [(m.obj.metric, m.n_compositions) for m in models if m.n_compositions < plan.min_compositions]
    result = dict(objectives=[o.__dict__ for o in objectives], plan=plan.__dict__, caveat=CAVEAT)
    if short:
        result.update(status="insufficient", decision="학습 조성이 부족해 후보를 제안하지 않는다: " +
                      ", ".join(f"{m} {n}개 (기준 {plan.min_compositions}개)" for m, n in short) +
                      ". 데이터 연결·측정 보강이 먼저다.")
        return result
    cands = generate(space, rules, plan.n_candidates, plan.seed)
    scr = screen(cands, rules)
    ok_ids = {p["id"] for p in scr["passed"]}
    cands = [c for c in cands if c["id"] in ok_ids]
    if not cands:
        result.update(status="no_feasible_candidates", decision="조성 규칙을 통과한 후보가 없다. 탐색 공간 또는 규칙을 점검한다.",
                      rejected=len(scr["rejected"]))
        return result
    preds = [m.predict(cands) for m in models]
    pts = [[preds[j][i]["mean"] for j in range(len(models))] for i in range(len(cands))]
    ranks = pareto_ranks(pts, [o.direction for o in objectives])
    rows = []
    for i, c in enumerate(cands):
        risk = max(p[i]["nn_ratio"] for p in preds)
        unseen = sorted({u for p in preds for u in p[i]["unseen"]})
        rows.append(dict(id=c["id"], components=c["components"], pareto_rank=ranks[i],
                         predictions={o.metric: dict(mean=round(preds[j][i]["mean"], 3), std=round(preds[j][i]["std"], 3))
                                      for j, o in enumerate(objectives)},
                         extrapolation_ratio=round(risk, 2), unseen_components=unseen,
                         risk="high" if (risk > plan.risk_threshold or unseen) else "normal",
                         status="pending_researcher_approval"))
    rows.sort(key=lambda r: (r["pareto_rank"], r["risk"] == "high", r["extrapolation_ratio"]))
    result.update(status="ok", generated=plan.n_candidates, rejected_by_rules=len(scr["rejected"]),
                  screened=len(cands), recommended=rows[:plan.top_k],
                  training={m.obj.metric: m.n_compositions for m in models},
                  decision="Pareto 상위 후보를 연구자 검토 대상으로 제안한다. 승인 전에는 실험하지 않는다.")
    return result


class DecisionLog:
    """연구자 결정 기록(append-only). 모듈 전용 DB 에 쓴다 — 읽기 전용 Adapter 연결과 분리한다."""

    def __init__(self, con):
        self.con = con
        con.execute("""CREATE TABLE IF NOT EXISTS doe_decisions(
            id INTEGER PRIMARY KEY AUTOINCREMENT, doe_id TEXT NOT NULL, candidate_id TEXT NOT NULL,
            reviewer TEXT NOT NULL, decision TEXT NOT NULL CHECK (decision IN ('approved','rejected','hold')),
            note TEXT, decided_at REAL NOT NULL)""")
        con.execute("""CREATE TRIGGER IF NOT EXISTS doe_decisions_no_update BEFORE UPDATE ON doe_decisions
            BEGIN SELECT RAISE(ABORT,'append-only'); END""")
        con.execute("""CREATE TRIGGER IF NOT EXISTS doe_decisions_no_delete BEFORE DELETE ON doe_decisions
            BEGIN SELECT RAISE(ABORT,'append-only'); END""")

    def record(self, doe_id, candidate_id, reviewer, decision, note=""):
        if not (reviewer or "").strip():
            raise ValueError("검토자 이름이 필요하다")
        self.con.execute("INSERT INTO doe_decisions(doe_id,candidate_id,reviewer,decision,note,decided_at) VALUES (?,?,?,?,?,?)",
                         (doe_id, candidate_id, reviewer.strip(), decision, note, time.time()))
        self.con.commit()

    def latest(self, doe_id):
        rows = self.con.execute("SELECT candidate_id,decision,reviewer,decided_at FROM doe_decisions WHERE doe_id=? ORDER BY id", (doe_id,))
        return {r[0]: dict(decision=r[1], reviewer=r[2], decided_at=r[3]) for r in rows}


def to_markdown(r):
    if r["status"] != "ok":
        return f"**{r['status']}**: {r['decision']}\n"
    objs = r["objectives"]
    head = ["후보", "Pareto", "외삽 위험"] + [f"{o['metric']} 예측({o['direction']})" for o in objs] + ["조성"]
    lines = ["| " + " | ".join(head) + " |", "|" + "---|" * len(head)]
    for c in r["recommended"]:
        comp = ", ".join(f"{x['name']} {x['amount']:g}{x['unit']}" for x in c["components"])
        pr = [f"{c['predictions'][o['metric']]['mean']} ± {c['predictions'][o['metric']]['std']}" for o in objs]
        lines.append("| " + " | ".join([c["id"], str(c["pareto_rank"]), f"{c['risk']} ({c['extrapolation_ratio']})"] + pr + [comp]) + " |")
    return (f"생성 {r['generated']} → 규칙 제외 {r['rejected_by_rules']} → 검토 {r['screened']} → 제안 {len(r['recommended'])}\n\n"
            + "\n".join(lines) + f"\n\n{r['decision']}\n\n{r['caveat']}\n")
