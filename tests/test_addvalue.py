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
        return av.compare(ad, "초기 DCIR", "mohm", PLAN)

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
            av.compare(ad, "고온저장 회복률", "%", PLAN)

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

    def test_min_improvement_is_required(self):
        with self.assertRaises(TypeError):
            av.Plan()


if __name__ == "__main__":
    unittest.main()
