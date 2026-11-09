"""가상 데이터로 모든 엔진을 실행해 단일 HTML(docs/overview.html)을 만든다. 외부 리소스·네트워크 없음.
사용: python scripts/build_report.py   (numpy·scikit-learn 필요)
"""
import html
import json
import sqlite3
import subprocess
import sys
import warnings
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
warnings.filterwarnings("ignore")

from electrolyte_platform import (synthetic, coverage, hub_contract, addvalue as av, doe_pipeline as dp,  # noqa: E402
                                  doe_constraints, evidence as ev)
from electrolyte_platform.adapters import SqlAdapter  # noqa: E402
from electrolyte_platform.composition import load_rules  # noqa: E402
from electrolyte_platform.gate import MixedConditionsError  # noqa: E402
from electrolyte_platform.materials import MaterialRegistry  # noqa: E402
from electrolyte_platform.registry import load_registry  # noqa: E402

e = html.escape
RULES = load_rules(ROOT / "configs/composition_rules.example.json")
REG = load_registry(ROOT / "configs/metric_registry.example.json")


def table(head, rows, cls=""):
    th = "".join(f"<th>{e(str(h))}</th>" for h in head)
    body = "".join("<tr>" + "".join(f"<td>{c if isinstance(c, Raw) else e(str(c))}</td>" for c in r) + "</tr>" for r in rows)
    return f'<div class="scroll"><table class="{cls}"><thead><tr>{th}</tr></thead><tbody>{body}</tbody></table></div>'


class Raw(str):
    pass


def badge(text, kind):
    return Raw(f'<span class="b {kind}">{e(text)}</span>')


def section(id_, title, lead, body):
    return f'<section id="{id_}"><h2>{e(title)}</h2><p class="lead">{lead}</p>{body}</section>'


def main():
    ad = SqlAdapter(synthetic.build(n_comp=80))
    ad_sig = SqlAdapter(synthetic.build(n_comp=80, signal="property"))
    parts = []

    # 1. 구조
    stages = [
        ("공통 DB 허브", "adapters · hub_contract · registry · composition", "읽기·점검", "part", "물질 ID → 조성 버전 → 제조 배치 → 실측 물성·셀 결과. 쓰기(환류)는 마지막 단계"),
        ("01 문헌·데이터 활용", "materials", "구현", "ok", "후보 검토 → 공통 Material ID → 조성 입력·DFT 입력"),
        ("02 유효인자 검증", "coverage · gate · addvalue", "구현", "ok", "현황표 → 조건 게이트 → 조성 단독 vs 조성+물성"),
        ("03 AI 분석·해석", "evidence", "구현(형식)", "part", "상관·예측 기여·기작 가설을 구분한 근거 패키지. 사내 해석 엔진 입력 형식은 확인 필요"),
        ("04 최적 DOE", "doe_constraints · doe_pipeline", "구현", "ok", "후보 생성 → 예측 → 규칙 검토 → Pareto → 연구자 결정"),
        ("05 검증·고도화", "(기존 Feedback Engine)", "환류 미구현", "todo", "승인된 실측 결과를 허브에 축적하는 경로는 마지막 단계"),
    ]
    cards = "".join(f'<div class="card"><div class="ct">{e(n)} {badge(s, k)}</div><code>{e(m)}</code><p>{e(d)}</p></div>' for n, m, s, k, d in stages)
    try:
        n_tests = subprocess.run([sys.executable, "-m", "pytest", "--collect-only", "-q", "-p", "no:cacheprovider", "tests"],
                                 cwd=ROOT, capture_output=True, text=True).stdout.strip().splitlines()[-1].split()[0] + "건"
    except Exception:
        n_tests = "?"
    parts.append(section("structure", "목표 구조와 구현 상태", "공개 근거와 사내 실측이 공통 내부 DB 허브를 중심으로 5단계를 지난다.",
                         f'<div class="cards">{cards}</div><p class="note">시험 {e(n_tests)} · 사내 데이터·사내 이름은 포함돼 있지 않다.</p>'))

    # 2. 허브 계약
    rows = hub_contract.check(ad, RULES)
    mark = {True: badge("충족", "ok"), False: badge("미충족", "bad"), None: badge("확인 불가", "part")}
    parts.append(section("hub", "허브 계약 점검", "물질 ID·조성 버전·배치·평가 조건·출처·QC 상태를 읽기 전용으로 점검한다. 열이 없으면 통과가 아니라 '확인 불가'.",
                         table(["계약 항목", "상태", "내용"], [(n, mark[ok], d) for n, ok, d in rows])))

    # 3. 현황표
    tab = coverage.build_table(ad, registry=REG)
    cr = []
    for t in tab:
        ex = sorted(t["exclusions"].items(), key=lambda kv: -kv[1])
        exs = ", ".join(f"{k} {v}" for k, v in ex[:3]) + (f" 외 {len(ex) - 3}" if len(ex) > 3 else "")
        cond = t["condition"] + (f"  ⚠ 조건 미기재: {', '.join(t['missing_conditions'])}" if t["missing_conditions"] else "")
        cr.append((t["metric"], cond, t["cell_rows"], t["compositions"], t["batches"], f"{t['complete_compositions']} / {t['complete_batches']}",
                   exs or "-", badge("예", "ok") if t["splittable"] else badge("아니오", "bad")))
    parts.append(section("coverage", "지표·조건별 데이터 연결 현황표", "셀 결과 행 수가 아니라 고유 조성·배치 수로 센다. real/RPT, retention/recovery는 합치지 않고, 필수 조건이 없는 행은 비교 불가로 표시한다.",
                         table(["지표", "평가 조건", "셀 행", "고유 조성", "배치", "물성 동시 확보 (조성/배치)", "주요 제외 사유", "분할 가능"], cr)
                         + f'<p class="rec"><b>추천</b> {e(coverage.recommend(tab))}</p>'))

    # 4. 게이트
    try:
        av.compare(ad, "고온저장/retention/용량", "%", av.Plan(0.5))
        gate_msg = "(차단되지 않음)"
    except MixedConditionsError as ex:
        gate_msg = str(ex)
    parts.append(section("gate", "평가 조건 게이트", "조건이 섞인 채로 분석하는 것을 막는다. 본체 v2.12 의 학습 데이터 선택은 metric+unit 만 보고 문자열 조건을 버린다(제안서: docs/PROPOSAL_protocol_gate_for_feature_hub.md).",
                         f'<div class="warn">차단: {e(gate_msg)}</div>'))

    # 5. 물성 추가 기여
    plan = av.Plan(0.5, n_repeats=6)
    res = {k: av.compare(a, "상온수명/real/용량유지율", "%", plan) for k, a in (("물성 효과 없음(가상)", ad), ("물성 효과 심음(가상)", ad_sig))}
    vmax = max(r["mae_dummy"] for r in res.values())
    blocks = ""
    for name, r in res.items():
        bars = "".join(f'<div class="bar"><span>{l}</span><i style="width:{v / vmax * 100:.0f}%"></i><b>{v:.2f}</b></div>'
                       for l, v in (("평균값 예측(참고)", r["mae_dummy"]), ("조성 단독", r["mae_base"]), ("조성+실측 물성", r["mae_plus"])))
        kind = "ok" if r["status"] == "adopt_candidate" else "part"
        blocks += (f'<div class="card"><div class="ct">{e(name)} {badge(r["status"], kind)}</div>{bars}'
                   f'<p>MAE 개선 {r["mean_improvement"]:+.2f} {e(r["unit"])} · 더 나았던 분할 {r["share_plus_better"]:.0%} · 고유 조성 {r["n_compositions"]}개</p>'
                   f'<p class="note">{e(r["decision"])}</p></div>')
    parts.append(section("addvalue", "물성의 추가 예측 기여", f"같은 표본·모델·분할에서 비교. 조성 그룹 단위 분할, 사전 기준(MAE 개선 ≥ {plan.min_improvement}, 일관성 {plan.min_consistency:.0%}). 막대는 검증 MAE(작을수록 좋음).",
                         f'<div class="cards two">{blocks}</div><p class="note">{e(av.CAVEAT)}</p>'))

    # 6. DOE
    space = dp.Space(salts={"LiPF6": [0.8, 1.4]}, solvents=["EC", "EMC", "DMC"], additives={"VC": [0, 2], "FEC": [0, 10]})
    objs = [dp.Objective("상온수명/real/용량유지율", "%", "max"), dp.Objective("상온수명/real/저항증가율", "%", "min")]
    d = dp.run(ad, objs, space, RULES, dp.DoePlan(n_candidates=300, top_k=6))
    dr = [(c["id"], c["pareto_rank"], badge(f"{c['risk']} ({c['extrapolation_ratio']})", "bad" if c["risk"] == "high" else "ok"),
           *(f"{c['predictions'][o.metric]['mean']} ± {c['predictions'][o.metric]['std']}" for o in objs),
           ", ".join(f"{x['name']} {x['amount']:g}{x['unit']}" for x in c["components"]), badge("승인 대기", "part")) for c in d["recommended"]]
    cand = [{"id": "OK", "components": d["recommended"][0]["components"]},
            {"id": "VC 과다·용매 합계 90", "components": [dict(component_class="salt", name="LiPF6", amount=1.0, unit="mol/L", basis="total_electrolyte"),
                                                         dict(component_class="solvent", name="EC", amount=30, unit="vol%", basis="total_electrolyte"),
                                                         dict(component_class="solvent", name="EMC", amount=60, unit="vol%", basis="total_electrolyte"),
                                                         dict(component_class="additive", name="VC", amount=5, unit="wt%", basis="total_electrolyte")]},
            {"id": "염을 wt% 로 표기", "components": [dict(component_class="salt", name="LiPF6", amount=12, unit="wt%", basis="x"),
                                                      dict(component_class="solvent", name="EC", amount=100, unit="vol%", basis="x")]}]
    sc = doe_constraints.screen(cand, RULES)
    rej = "".join(f"<li><b>{e(r['id'])}</b> 제외 — " + e("; ".join(f"[{c}] {m}" for c, m in r["issues"])) + "</li>" for r in sc["rejected"])
    parts.append(section("doe", "최적 DOE 후보 도출", "규칙(염 mol/L · 용매 vol% 합계 100 · 첨가제 wt%)을 지키는 후보만 예측·Pareto 로 보낸다. 아직 제조하지 않은 후보이므로 조성 단독 예측이며, 모든 후보는 연구자 승인 대기.",
                         f'<p class="note">생성 {d["generated"]} → 규칙 제외 {d["rejected_by_rules"]} → 검토 {d["screened"]} → 제안 {len(d["recommended"])}</p>'
                         + table(["후보", "Pareto", "외삽 위험", "용량유지율 예측(max)", "저항증가율 예측(min)", "조성", "상태"], dr)
                         + f'<h3>규칙 검토 예</h3><ul class="plain"><li>통과 {len(sc["passed"])}개: 연구자 승인 대기</li>{rej}</ul>'
                         f'<p class="note">{e(dp.CAVEAT)}</p>'))

    # 7. 물질 등록
    con = sqlite3.connect(":memory:"); con.row_factory = sqlite3.Row
    r = MaterialRegistry(con)
    steps = []
    c = r.propose("Fluoroethylene carbonate", "additive", "SEI 형성 첨가제로 보고", "10.0000/example", "FEC improved cycling (가상 인용)", cas="114435-02-8", smiles="O=C1OCC(F)O1")
    steps.append(("제안", f"후보 #{c}: 구조·역할·DOI·원문 근거 필수, CAS 검산 통과", "candidate"))
    try:
        r.register(c)
    except ValueError as ex:
        steps.append(("승인 전 등록 시도", f"거부: {ex}", "bad"))
    r.review(c, "연구자 A", "approved", "구조·출처 확인")
    mid, new = r.register(c)
    steps.append(("승인 → 등록", f"{mid} ({'신규' if new else '기존'})", "ok"))
    r.add_alias(mid, "FEC")
    comp = r.component_for("FEC", 2.0, "wt%")
    steps.append(("조성 입력", f"FEC → material_id={comp['material_id']}", "ok"))
    dft = r.dft_input(mid, charge=0, multiplicity=1, method="B3LYP/6-31G*")
    steps.append(("DFT 입력", f"같은 ID {dft['material_id']} · 상태 {dft['status']}", "ok"))
    try:
        r.component_for("LiNewSalt", 1.0, "mol/L")
    except KeyError as ex:
        steps.append(("미등록 물질", f"거부: {ex.args[0]}", "bad"))
    try:
        r.dft_input(mid, charge=None, multiplicity=1, method="B3LYP")
    except ValueError as ex:
        steps.append(("DFT 조건 누락", f"거부: {ex}", "bad"))
    parts.append(section("materials", "문헌 후보 → 공통 Material ID", "승인된 후보만 등록되고, 조성 입력과 DFT 입력이 같은 ID 를 쓴다. DFT 는 입력 명세만 만들며 계산·수렴은 검증하지 않는다.",
                         table(["단계", "결과"], [(s, Raw(f"{badge({'ok': '통과', 'bad': '거부', 'candidate': '대기'}[k], k)} {e(t)}")) for s, t, k in steps])
                         + f'<pre>{e(json.dumps(dft, ensure_ascii=False, indent=1))}</pre>'))

    # 8. 근거 패키지
    item = ev.from_addvalue(res["물성 효과 심음(가상)"])
    pkg = ev.package([item, ev.hypothesis_item("전도도가 높은 배치에서 이온 이동이 수명 지표에 기여했을 가능성(검증 전 가설)", [0], "연구자 가설")], "물성이 수명 예측에 기여하는가")
    bad = ev.association_item("M", "%", "25C", 30, 40, "conductivity", 0.5, "합성"); bad.statement = "전도도가 수명 저하의 원인이다"
    try:
        ev.package([bad]); err = "-"
    except ValueError as ex:
        err = str(ex)
    parts.append(section("evidence", "해석 엔진용 근거 패키지", "상관·예측 기여·기작 가설을 섞지 않는다. 가설에는 수치를 직접 붙일 수 없고, 한계 항목은 필수.",
                         table(["#", "종류", "상태", "진술", "표본(조성/배치)"], [(i, it["kind"], it["status"], it["statement"], f"{it['n_compositions']}/{it['n_batches']}") for i, it in enumerate(pkg["items"])])
                         + f'<div class="warn">인과 표현 거부 예: {e(err)}</div>'))

    nav = "".join(f'<a href="#{i}">{e(t)}</a>' for i, t in (("structure", "구조"), ("hub", "허브"), ("coverage", "현황표"), ("gate", "게이트"), ("addvalue", "물성 기여"), ("doe", "DOE"), ("materials", "물질"), ("evidence", "근거")))
    page = f"""<!doctype html><html lang="ko"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Electrolyte AI Platform 구조 프로토타입</title><style>{CSS}</style></head><body>
<header><h1>Electrolyte AI Platform · 구조 프로토타입</h1>
<div class="synth">⚠ 모든 수치는 <b>가상 데이터</b>로 실행한 결과다. 구조·규칙 동작 확인용이며 실제 연구 결과가 아니다. · 생성 {date.today().isoformat()}</div>
<nav>{nav}</nav></header><main>{''.join(parts)}</main></body></html>"""
    out = ROOT / "docs/overview.html"
    out.write_text(page, encoding="utf-8")
    print(out, len(page) // 1024, "KB")


CSS = """
:root{--bg:#fff;--fg:#1c2330;--mut:#5b6678;--line:#dde3ec;--card:#f6f8fb;--acc:#1f6feb;--ok:#1a7f4b;--okb:#e4f5ec;--bad:#b42318;--badb:#fde8e6;--part:#9a6700;--partb:#fff3d1;--warnb:#fff3d1}
@media(prefers-color-scheme:dark){:root{--bg:#10151d;--fg:#e6ebf2;--mut:#9aa6b8;--line:#2a3342;--card:#171e29;--acc:#6ea8ff;--ok:#5fd394;--okb:#12301f;--bad:#ff8d82;--badb:#3a1814;--part:#e8b94a;--partb:#3a2f10;--warnb:#3a2f10}}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--fg);font:15px/1.6 system-ui,-apple-system,"Segoe UI","Noto Sans KR",sans-serif}
header{padding:20px 16px 0;max-width:1100px;margin:auto}h1{margin:0 0 8px;font-size:22px}
.synth{background:var(--warnb);border:1px solid var(--line);border-radius:8px;padding:8px 12px;font-size:13px}
nav{display:flex;flex-wrap:wrap;gap:6px;margin:12px 0;position:sticky;top:0;background:var(--bg);padding:8px 0;border-bottom:1px solid var(--line)}
nav a{color:var(--acc);text-decoration:none;padding:3px 10px;border:1px solid var(--line);border-radius:99px;font-size:13px}
main p,main li,main .warn{overflow-wrap:anywhere}main{max-width:1100px;margin:auto;padding:0 16px 60px}section{margin-top:34px}h2{font-size:18px;margin:0 0 4px}h3{font-size:15px;margin:18px 0 6px}
.lead{color:var(--mut);margin:0 0 12px}.note{color:var(--mut);font-size:13px}.rec{background:var(--card);border-left:3px solid var(--acc);padding:8px 12px;border-radius:4px}
.scroll{overflow-x:auto;border:1px solid var(--line);border-radius:8px}table{border-collapse:collapse;width:100%;font-size:13px}
th,td{padding:7px 10px;border-bottom:1px solid var(--line);text-align:left;vertical-align:top}th{background:var(--card);white-space:nowrap}tr:last-child td{border-bottom:0}
.cards{display:grid;grid-template-columns:repeat(auto-fill,minmax(min(260px,100%),1fr));gap:12px}.cards.two{grid-template-columns:repeat(auto-fit,minmax(min(320px,100%),1fr))}.cards>*{min-width:0}
.card{overflow-wrap:anywhere;background:var(--card);border:1px solid var(--line);border-radius:10px;padding:12px 14px}.ct{font-weight:600;margin-bottom:4px;display:flex;gap:8px;flex-wrap:wrap;align-items:center}.card p{margin:6px 0 0;font-size:13px}
code{font-size:12px;color:var(--mut)}pre{background:var(--card);border:1px solid var(--line);border-radius:8px;padding:10px;overflow:auto;font-size:12px}
.b{font-size:11px;font-weight:600;padding:1px 8px;border-radius:99px;border:1px solid currentColor;white-space:nowrap}.b.ok{color:var(--ok);background:var(--okb)}.b.bad{color:var(--bad);background:var(--badb)}.b.part,.b.todo,.b.candidate{color:var(--part);background:var(--partb)}
.warn{background:var(--badb);color:var(--bad);border-radius:8px;padding:10px 12px;font-size:13px;margin:8px 0}ul.plain{margin:4px 0;padding-left:18px;font-size:13px}
.bar{display:grid;grid-template-columns:minmax(80px,120px) 1fr 44px;gap:8px;align-items:center;font-size:12px;margin:6px 0}.bar i{display:block;height:10px;background:var(--acc);border-radius:5px}.bar b{text-align:right}
"""

main()
