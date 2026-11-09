import sqlite3
import unittest
import warnings
try:
    import sklearn  # noqa
    HAVE = True
except ImportError:
    HAVE = False
from electrolyte_platform import synthetic
from electrolyte_platform import doe_pipeline as dp
from electrolyte_platform.adapters import SqlAdapter
from electrolyte_platform.composition import Rules, validate, load_rules

warnings.filterwarnings("ignore")
RULES = load_rules("configs/composition_rules.example.json")
SPACE = dp.Space(salts={"LiPF6": [0.8, 1.4]}, solvents=["EC", "EMC", "DMC"], additives={"VC": [0, 2], "FEC": [0, 10]})
OBJ = dp.Objective("상온수명/real/용량유지율", "%", "max")


class Pure(unittest.TestCase):
    def test_pareto_ranks(self):
        r = dp.pareto_ranks([[1, 1], [2, 2], [3, 0], [0.5, 0.5]], ["max", "max"])
        self.assertEqual(r, [2, 1, 1, 3])
        self.assertEqual(dp.pareto_ranks([[1, 5], [2, 4]], ["max", "min"]), [2, 1])

    def test_generated_candidates_follow_conventions(self):
        for c in dp.generate(SPACE, RULES, 100, seed=3):
            codes = {x for x, _ in validate(c["components"], RULES)}
            self.assertFalse(codes & {"UNIT", "SOLVENT_SUM", "NEGATIVE", "BASIS"}, codes)

    def test_decision_log_is_append_only_and_needs_reviewer(self):
        log = dp.DecisionLog(sqlite3.connect(":memory:"))
        log.record("DOE-1", "C1", "홍길동", "approved", "ok")
        with self.assertRaises(ValueError):
            log.record("DOE-1", "C2", " ", "approved")
        with self.assertRaises(sqlite3.IntegrityError):
            log.record("DOE-1", "C2", "x", "maybe")
        with self.assertRaises(sqlite3.DatabaseError):
            log.con.execute("UPDATE doe_decisions SET decision='rejected'")
        with self.assertRaises(sqlite3.DatabaseError):
            log.con.execute("DELETE FROM doe_decisions")
        self.assertEqual(log.latest("DOE-1")["C1"]["decision"], "approved")


@unittest.skipUnless(HAVE, "scikit-learn 필요")
class Pipeline(unittest.TestCase):
    def setUp(self):
        self.ad = SqlAdapter(synthetic.build(n_comp=80))

    def test_end_to_end_pending_approval_only(self):
        r = dp.run(self.ad, [OBJ, dp.Objective("상온수명/real/저항증가율", "%", "min")], SPACE, RULES,
                   dp.DoePlan(n_candidates=200, top_k=5))
        self.assertEqual(r["status"], "ok")
        self.assertEqual(len(r["recommended"]), 5)
        self.assertTrue(all(c["status"] == "pending_researcher_approval" for c in r["recommended"]))
        self.assertTrue(all(c["pareto_rank"] >= 1 for c in r["recommended"]))
        self.assertEqual(r["recommended"][0]["pareto_rank"], 1)

    def test_insufficient_training_data_proposes_nothing(self):
        r = dp.run(self.ad, [dp.Objective("상온수명/real/저항증가율", "%", "min")], SPACE, RULES,
                   dp.DoePlan(n_candidates=50, min_compositions=500))
        self.assertEqual(r["status"], "insufficient")
        self.assertNotIn("recommended", r)

    def test_unseen_component_and_far_candidate_flagged_high_risk(self):
        m = dp.CompositionModel(self.ad, OBJ)
        far = {"id": "far", "components": [
            dict(component_class="salt", name="LiTFSI", amount=1.0, unit="mol/L", basis="total_electrolyte"),
            dict(component_class="solvent", name="EC", amount=100, unit="vol%", basis="total_electrolyte")]}
        p = m.predict([far])[0]
        self.assertIn("cmp::salt::LiTFSI::mol/L::total_electrolyte", p["unseen"])
        self.assertGreater(p["nn_ratio"], 1.5)

    def test_rules_filter_before_prediction(self):
        tight = Rules(solvent_tol=0.0, allowed_names={"solvent": ["EC"]})     # 용매가 EC 하나뿐이어야 통과
        r = dp.run(self.ad, [OBJ], SPACE, tight, dp.DoePlan(n_candidates=50))
        self.assertEqual(r["status"], "no_feasible_candidates")


if __name__ == "__main__":
    unittest.main()
