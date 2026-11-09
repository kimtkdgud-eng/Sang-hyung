import json
import os
import tempfile
import unittest
from electrolyte_platform import synthetic, hub_contract, doe_constraints
from electrolyte_platform.adapters import SqlAdapter
from electrolyte_platform.composition import Rules, load_rules, validate


def C(cls, name, amt, unit, basis="total_electrolyte"):
    return dict(component_class=cls, name=name, amount=amt, unit=unit, basis=basis)


GOOD = [C("salt", "LiPF6", 1.0, "mol/L"), C("solvent", "EC", 30, "vol%"), C("solvent", "EMC", 70, "vol%"),
        C("additive", "VC", 1, "wt%")]
codes = lambda comps, rules=None: {c for c, _ in validate(comps, rules or Rules())}


class T(unittest.TestCase):
    def test_good_passes(self):
        self.assertEqual(codes(GOOD), set())

    def test_closure_applies_to_solvent_only(self):
        # 염·첨가제는 합계 100 에 포함되지 않는다: 용매만 100이면 통과
        self.assertEqual(codes(GOOD + [C("additive", "FEC", 10, "wt%")]), set())
        self.assertIn("SOLVENT_SUM", codes([GOOD[0], C("solvent", "EC", 30, "vol%"), C("solvent", "EMC", 60, "vol%")]))

    def test_units_not_converted(self):
        self.assertIn("UNIT", codes([C("salt", "LiPF6", 12, "wt%")] + GOOD[1:]))
        self.assertIn("UNIT", codes([GOOD[0], C("solvent", "EC", 30, "wt%"), C("solvent", "EMC", 70, "wt%")]))

    def test_range_allowed_incompatible_negative_total(self):
        r = Rules(ranges={"additive::VC": [0, 3]}, allowed_names={"solvent": ["EC"]},
                  incompatible=[["VC", "FEC"]], additive_total_max=2.0)
        got = codes(GOOD + [C("additive", "FEC", 5, "wt%")], r)
        self.assertTrue({"NOT_ALLOWED", "INCOMPATIBLE", "ADDITIVE_TOTAL"} <= got)
        self.assertIn("RANGE", codes([GOOD[0], GOOD[1], GOOD[2], C("additive", "VC", 5, "wt%")], r))
        self.assertIn("NEGATIVE", codes(GOOD[:3] + [C("additive", "VC", -1, "wt%")]))

    def test_basis_checked_only_when_configured(self):
        bad = GOOD[:3] + [C("additive", "VC", 1, "wt%", basis="solvent")]
        self.assertEqual(codes(bad), set())
        self.assertIn("BASIS", codes(bad, Rules(basis_by_class={"additive": "total_electrolyte"})))

    def test_load_rules_ignores_notes(self):
        with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False, encoding="utf-8") as f:
            json.dump({"_note": "x", "solvent_tol": 1.0}, f)
        try:
            self.assertEqual(load_rules(f.name).solvent_tol, 1.0)
        finally:
            os.unlink(f.name)

    def test_screen_never_auto_approves(self):
        res = doe_constraints.screen([{"id": "ok", "components": GOOD}, {"id": "bad", "components": GOOD[:1]}], Rules())
        self.assertEqual([p["status"] for p in res["passed"]], ["pending_researcher_approval"])
        self.assertEqual(res["rejected"][0]["id"], "bad")

    def test_hub_contract_reports_unknowns_not_pass(self):
        rows = {n: ok for n, ok, _ in hub_contract.check(SqlAdapter(synthetic.build()), Rules())}
        self.assertIsNone(rows["조성 버전"])      # 열이 없으면 '확인 불가'
        self.assertIsNone(rows["QC 상태"])
        self.assertFalse(rows["결과 → 제조 배치"])  # 가상 데이터에 일부러 넣은 누락
        self.assertTrue(rows["조성 표기 규칙"])


if __name__ == "__main__":
    unittest.main()
