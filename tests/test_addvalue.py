import unittest
import warnings
try:
    import sklearn  # noqa
    HAVE = True
except ImportError:
    HAVE = False
from electrolyte_platform import synthetic
from electrolyte_platform.adapters import SqlAdapter
from electrolyte_platform.gate import MixedConditionsError
from electrolyte_platform import addvalue as av
from tests.helpers import mk, cell, full_props

warnings.filterwarnings("ignore")
PLAN = av.Plan(min_improvement=0.5, n_repeats=4)


@unittest.skipUnless(HAVE, "scikit-learn 필요")
class T(unittest.TestCase):
    def run_dcir(self, signal):
        ad = SqlAdapter(synthetic.build(signal=signal, n_comp=80))
        return av.compare(ad, "상온수명/real/용량유지율", "%", PLAN)

    def test_no_signal_keeps_optional(self):
        r = self.run_dcir("none")
        self.assertEqual(r["status"], "keep_optional")

    def test_property_signal_detected(self):
        r = self.run_dcir("property")
        self.assertEqual(r["status"], "adopt_candidate")
        self.assertGreater(r["mean_improvement"], 0.5)

    def test_mixed_conditions_blocked(self):
        ad = SqlAdapter(synthetic.build())
        with self.assertRaises(MixedConditionsError):
            av.compare(ad, "고온저장/retention/용량", "%", PLAN)

    def test_insufficient_samples_do_not_train(self):
        con = mk(); cell(con, "a", "C1", "B1"); full_props(con, "B1")
        r = av.compare(SqlAdapter(con), "M", "%", PLAN)
        self.assertEqual(r["status"], "insufficient")
        self.assertNotIn("mae_base", r)

    def test_same_recipe_never_in_train_and_test(self):
        # 조성별로 값이 크게 다르고 배치마다 약간 다를 때, 누수가 있으면 MAE 가 비정상적으로 낮아진다.
        con = mk(recipes=tuple(f"C{i}" for i in range(30)),
                 batches=tuple((f"B{i}_{j}", f"C{i}") for i in range(30) for j in range(3)))
        for i in range(30):
            for j in range(3):
                b = f"B{i}_{j}"
                cell(con, f"t{i}{j}", f"C{i}", b, v=(i * 7919 % 100) + j * 0.01)
                full_props(con, b)
        r = av.compare(SqlAdapter(con), "M", "%", PLAN)
        self.assertGreater(r["mae_base"], 5.0)           # 새 조성을 못 맞춘다 = 누수 없음

    def test_bootstrap_ci_detects_zero_straddling(self):
        lo, hi = av.paired_bootstrap_ci([1.0, 1.2, 0.9, 1.1, 1.0, 0.8], seed=1)
        self.assertGreater(lo, 0)
        lo, hi = av.paired_bootstrap_ci([1.0, -1.0, 0.8, -0.9, 0.2, -0.3, 0.5, -0.6], seed=1)
        self.assertLess(lo, 0); self.assertGreater(hi, 0)
        self.assertEqual(av.paired_bootstrap_ci([1, -1, 2, -2], seed=3), av.paired_bootstrap_ci([1, -1, 2, -2], seed=3))

    def test_decision_requires_ci_not_only_mean(self):
        # 평균이 기준을 넘어도 신뢰구간이 0을 가로지르면 채택하지 않는다 (표본이 작고 잡음이 큰 경우)
        r = av.compare(SqlAdapter(synthetic.build(signal="property", n_comp=80)), "상온수명/real/용량유지율", "%",
                       av.Plan(min_improvement=0.5, n_repeats=3, n_boot=500))
        self.assertGreater(r["ci_low"], 0)
        self.assertEqual(r["status"], "adopt_candidate")
        r["ci_low"] = -0.1                      # 같은 평균이어도 하한이 0 아래면 규칙상 채택 불가임을 규칙으로 확인
        self.assertFalse(r["mean_improvement"] >= r["plan"]["min_improvement"] and r["ci_low"] > 0)

    def test_material_holdouts_are_leak_free(self):
        samples, _, _ = av.build_samples(SqlAdapter(synthetic.build(n_comp=80)), "상온수명/real/용량유지율", "%")
        holds = av.material_holdouts(samples, 5, 10)
        self.assertTrue(holds)
        for m, tr, te in holds:
            self.assertFalse({samples[i]["recipe_id"] for i in tr} & {samples[i]["recipe_id"] for i in te})
            for i in tr:
                self.assertFalse(any(k.split("::")[2] == m and v > 0 for k, v in samples[i]["comp"].items()))
            for i in te:
                self.assertTrue(any(k.split("::")[2] == m and v > 0 for k, v in samples[i]["comp"].items()))

    def test_mediated_effect_is_material_specific_and_judged_per_material(self):
        ad = SqlAdapter(synthetic.build(signal="mediated", n_comp=120))
        plan = dict(min_improvement=0.5, n_repeats=3, n_boot=1000)
        same = av.compare(ad, "상온수명/real/용량유지율", "%", av.Plan(**plan))
        new = av.compare(ad, "상온수명/real/용량유지율", "%", av.Plan(split="material", **plan))
        self.assertEqual(new["status"], "adopt_candidate")
        by = {b["material"]: b for b in new["by_material"]}
        self.assertTrue(by["FEC"]["helps"])                                  # 효과가 전도도를 거치는 물질
        self.assertFalse(any(b["helps"] for m, b in by.items() if m != "FEC"))
        self.assertGreater(by["FEC"]["mean_improvement"], same["mean_improvement"])
        self.assertGreater(new["ci_level_adjusted"], 0.95)                   # 본페로니: 물질 수만큼 더 엄격
        self.assertLess(new["ci_level_adjusted"], 1.0)

    def test_no_effect_data_not_adopted_in_material_split(self):
        for seed in (0, 1, 2):
            ad = SqlAdapter(synthetic.build(signal="none", n_comp=120, seed=seed))
            r = av.compare(ad, "상온수명/real/용량유지율", "%", av.Plan(0.5, n_repeats=2, n_boot=500, split="material"))
            self.assertEqual(r["status"], "keep_optional", f"seed {seed}")

    def test_material_split_insufficient_when_no_material_can_be_held_out(self):
        con = mk(recipes=tuple(f"C{i}" for i in range(25)), batches=tuple((f"B{i}", f"C{i}") for i in range(25)))
        for i in range(25):
            cell(con, f"t{i}", f"C{i}", f"B{i}", v=80 + i); full_props(con, f"B{i}")
        r = av.compare(SqlAdapter(con), "M", "%", av.Plan(0.5, split="material"))      # 모든 조성에 같은 물질 -> 뺄 수 없음
        self.assertEqual(r["status"], "insufficient")

    def test_min_improvement_is_required(self):
        with self.assertRaises(TypeError):
            av.Plan()


if __name__ == "__main__":
    unittest.main()
