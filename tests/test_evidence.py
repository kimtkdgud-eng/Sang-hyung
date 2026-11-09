import unittest
import warnings
try:
    import sklearn  # noqa
    HAVE = True
except ImportError:
    HAVE = False
from electrolyte_platform import evidence as ev, synthetic
from electrolyte_platform.adapters import SqlAdapter

warnings.filterwarnings("ignore")


def assoc(**kw):
    d = dict(metric="M", unit="%", condition="25C", n_compositions=30, n_batches=40, feature="conductivity", rho=0.5, source="FTI v0.2 synthetic")
    d.update(kw)
    return ev.association_item(**d)


class T(unittest.TestCase):
    def test_hypothesis_cannot_carry_numbers_or_skip_status(self):
        h = ev.hypothesis_item("점도 증가가 이온 이동을 제한할 수 있다", [0], "내부 검토")
        h.numbers = {"rho": 0.9}
        self.assertTrue(any("수치" in e for e in ev.validate(h, 1, 2)))
        h2 = ev.hypothesis_item("가설", [0], "내부"); h2.status = "supported"
        self.assertTrue(any("hypothesis_untested" in e for e in ev.validate(h2, 1, 2)))

    def test_association_cannot_claim_causation(self):
        a = assoc(); a.statement = "전도도가 수명 저하의 원인이다. 인과 관계가 입증됐다"
        self.assertTrue(any("인과" in e for e in ev.validate(a, 0, 1)))

    def test_association_requires_confounding_limit_and_condition(self):
        a = assoc(); a.limits = ["참고용"]; a.condition = ""
        errs = ev.validate(a, 0, 1)
        self.assertTrue(any("교란" in e for e in errs)); self.assertTrue(any("평가 조건" in e for e in errs))

    def test_hypothesis_supports_must_reference_existing_items(self):
        h = ev.hypothesis_item("가설", [5], "내부")
        with self.assertRaises(ValueError):
            ev.package([assoc(), h])
        self.assertEqual(ev.package([assoc(), ev.hypothesis_item("가설", [0], "내부")])["counts"]["mechanism_hypothesis"], 1)

    def test_package_refuses_when_any_item_invalid(self):
        bad = assoc(); bad.limits = []
        with self.assertRaises(ValueError) as e:
            ev.package([assoc(), bad])
        self.assertIn("[1]", str(e.exception))

    @unittest.skipUnless(HAVE, "scikit-learn 필요")
    def test_from_addvalue_roundtrip_and_incomplete_results_rejected(self):
        from electrolyte_platform import addvalue as av
        ad = SqlAdapter(synthetic.build(signal="property", n_comp=80))
        r = av.compare(ad, "상온수명/real/용량유지율", "%", av.Plan(0.5, n_repeats=3))
        item = ev.from_addvalue(r)
        self.assertEqual(item.kind, "predictive_contribution")
        self.assertEqual(item.numbers["min_improvement"], 0.5)
        pkg = ev.package([item, ev.hypothesis_item("전도도 경로의 이온 이동이 기여했을 수 있다", [0], "연구자 가설")], "물성이 수명 예측에 기여하는가")
        self.assertEqual(pkg["counts"], {"association": 0, "predictive_contribution": 1, "mechanism_hypothesis": 1})
        self.assertIn("제조하지 않은", " ".join(pkg["items"][0]["limits"]))
        r["status"] = "insufficient"
        with self.assertRaises(ValueError):
            ev.from_addvalue(r)


if __name__ == "__main__":
    unittest.main()
