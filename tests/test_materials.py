import sqlite3
import unittest
from electrolyte_platform.materials import MaterialRegistry, cas_valid
from electrolyte_platform.composition import Rules, validate


def reg():
    con = sqlite3.connect(":memory:")
    con.row_factory = sqlite3.Row
    return MaterialRegistry(con)


def prop(r, name="Fluoroethylene carbonate", cls="additive", cas="114435-02-8", smiles="O=C1OCC(F)O1"):
    return r.propose(name, cls, "SEI 형성 첨가제로 보고", "10.0000/example", "FEC improved cycling", cas=cas, smiles=smiles)


class T(unittest.TestCase):
    def test_cas_checksum(self):
        self.assertTrue(cas_valid("96-49-1"))        # ethylene carbonate
        self.assertFalse(cas_valid("96-49-2"))
        self.assertFalse(cas_valid("abc"))

    def test_proposal_needs_evidence(self):
        r = reg()
        with self.assertRaises(ValueError):
            r.propose("X", "additive", "역할", "", "근거")
        with self.assertRaises(ValueError):
            r.propose("X", "additive", "역할", "10.1/x", "근거", cas="96-49-2")
        with self.assertRaises(ValueError):
            r.propose("X", "polymer", "역할", "10.1/x", "근거")

    def test_must_be_approved_before_registration(self):
        r = reg(); c = prop(r)
        with self.assertRaises(ValueError):
            r.register(c)
        with self.assertRaises(ValueError):
            r.review(c, "", "approved")
        r.review(c, "홍길동", "approved", "구조·출처 확인")
        mid, new = r.register(c)
        self.assertTrue(new)
        self.assertEqual(r.resolve("fluoroethylene carbonate"), mid)
        with self.assertRaises(ValueError):
            r.register(c)

    def test_rejected_cannot_register(self):
        r = reg(); c = prop(r)
        r.review(c, "홍길동", "rejected", "구조 불일치")
        with self.assertRaises(ValueError):
            r.register(c)

    def test_same_material_reuses_id_and_keeps_both_sources(self):
        r = reg()
        c1 = prop(r); r.review(c1, "a", "approved"); m1, _ = r.register(c1)
        c2 = r.propose("FEC", "additive", "다른 논문 역할", "10.1/other", "근거2", cas="114435-02-8")
        r.review(c2, "a", "approved"); m2, new = r.register(c2)
        self.assertEqual(m1, m2); self.assertFalse(new)
        self.assertEqual(len(r.get(m1)["sources"]), 2)
        self.assertEqual(r.resolve("fec"), m1)

    def test_class_conflict_is_blocked(self):
        r = reg()
        c1 = prop(r); r.review(c1, "a", "approved"); r.register(c1)
        c2 = prop(r, cls="solvent"); r.review(c2, "a", "approved")
        with self.assertRaises(ValueError):
            r.register(c2)

    def test_same_id_for_composition_and_dft(self):
        r = reg(); c = prop(r); r.review(c, "a", "approved"); mid, _ = r.register(c)
        r.add_alias(mid, "FEC")
        comp = r.component_for("FEC", 2.0, "wt%")
        self.assertEqual(comp["material_id"], mid)
        dft = r.dft_input(mid, charge=0, multiplicity=1, method="B3LYP/6-31G*")
        self.assertEqual(dft["material_id"], comp["material_id"])
        self.assertEqual(dft["status"], "input_only_not_run")
        # 조성 규칙 검증에도 등록 물질 목록을 그대로 쓸 수 있다
        rules = Rules(allowed_names=r.allowed_names())
        issues = validate([comp, dict(component_class="solvent", name="EC", amount=100, unit="vol%", basis="x")], rules)
        self.assertIn("NOT_ALLOWED", {c for c, _ in issues})      # EC 는 아직 등록 안 됨 -> 드러난다

    def test_alias_conflict_blocked(self):
        r = reg()
        c1 = prop(r); r.review(c1, "a", "approved"); m1, _ = r.register(c1)
        c2 = prop(r, name="Vinylene carbonate", cas="872-36-6", smiles="O=C1OC=CO1"); r.review(c2, "a", "approved"); m2, _ = r.register(c2)
        self.assertNotEqual(m1, m2)
        r.add_alias(m2, "VC")
        with self.assertRaises(ValueError):
            r.add_alias(m1, "VC")

    def test_unregistered_name_is_refused_not_created(self):
        r = reg()
        with self.assertRaises(KeyError):
            r.component_for("LiNewSalt", 1.0, "mol/L")

    def test_dft_input_requires_conditions(self):
        r = reg(); c = prop(r, smiles=None); r.review(c, "a", "approved"); mid, _ = r.register(c)
        with self.assertRaises(ValueError) as e:
            r.dft_input(mid, charge=None, multiplicity=1, method="B3LYP")
        self.assertIn("SMILES", str(e.exception)); self.assertIn("전하", str(e.exception))


if __name__ == "__main__":
    unittest.main()
