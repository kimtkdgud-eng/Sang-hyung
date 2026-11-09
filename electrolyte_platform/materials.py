"""01 물질 등록 엔진: 공개 문헌 후보 -> 검토 -> 공통 Material ID -> 조성 입력·DFT 입력에서 같은 ID 사용.

- 후보는 구조·문헌 내 역할·출처(DOI)·원문 근거가 있어야 제안할 수 있고, 연구자가 승인해야 등록된다.
- 같은 물질(CAS 또는 구조 SMILES 또는 정규화한 이름이 일치)은 새 ID 를 만들지 않고 기존 ID 로 연결한다.
- 이 모듈은 공개 자료 쪽이다: 사내 조성·결과를 받지 않는다. 사내 허브 반영은 export_rows() 결과를 사내 절차로 가져간다.
- DFT 는 입력만 만든다. 계산 수렴·정확도는 검증하지 않으며, 전하·스핀다중도·방법이 없으면 입력을 만들지 않는다.
- RDKit 등으로 구조를 검증하지 않는다(SMILES 는 문자열로 보존). 구조 검증은 후속 과제다.
"""
import re
import time

CLASSES = ("salt", "solvent", "additive")


def cas_valid(cas):
    m = re.fullmatch(r"(\d{2,7})-(\d{2})-(\d)", cas or "")
    if not m:
        return False
    digits = (m.group(1) + m.group(2))[::-1]
    return sum(int(d) * (i + 1) for i, d in enumerate(digits)) % 10 == int(m.group(3))


def norm(name):
    return re.sub(r"[\s\-_()\[\],]", "", (name or "").lower())


class MaterialRegistry:
    def __init__(self, con):
        self.con = con
        con.executescript("""
        CREATE TABLE IF NOT EXISTS material_candidates(
            candidate_id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT NOT NULL, cas TEXT, smiles TEXT,
            proposed_class TEXT NOT NULL, role_in_source TEXT NOT NULL, source_doi TEXT NOT NULL, source_quote TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'candidate' CHECK (status IN ('candidate','approved','rejected','registered')),
            reviewer TEXT, review_note TEXT, created_at REAL NOT NULL, reviewed_at REAL);
        CREATE TABLE IF NOT EXISTS materials(
            material_id TEXT PRIMARY KEY, name TEXT NOT NULL, material_class TEXT NOT NULL, cas TEXT, smiles TEXT,
            source_candidate_id INTEGER, registered_at REAL NOT NULL);
        CREATE TABLE IF NOT EXISTS material_aliases(alias_norm TEXT PRIMARY KEY, material_id TEXT NOT NULL, alias TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS material_sources(
            id INTEGER PRIMARY KEY AUTOINCREMENT, material_id TEXT NOT NULL, source_doi TEXT NOT NULL, role_in_source TEXT, source_quote TEXT);
        """)

    # ---- 제안 -> 검토 -> 등록
    def propose(self, name, proposed_class, role_in_source, source_doi, source_quote, cas=None, smiles=None):
        if proposed_class not in CLASSES:
            raise ValueError(f"구분은 {CLASSES} 중 하나여야 한다")
        for label, v in (("이름", name), ("문헌 내 역할", role_in_source), ("출처 DOI", source_doi), ("원문 근거", source_quote)):
            if not (v or "").strip():
                raise ValueError(f"{label}이(가) 필요하다")
        if cas and not cas_valid(cas):
            raise ValueError(f"CAS 번호 형식·검산 오류: {cas}")
        if smiles is not None and (not smiles.strip() or re.search(r"\s", smiles)):
            raise ValueError("SMILES 에 공백이 있거나 비어 있다")
        cur = self.con.execute(
            "INSERT INTO material_candidates(name,cas,smiles,proposed_class,role_in_source,source_doi,source_quote,created_at)"
            " VALUES (?,?,?,?,?,?,?,?)", (name.strip(), cas, smiles, proposed_class, role_in_source.strip(),
                                         source_doi.strip(), source_quote.strip(), time.time()))
        self.con.commit()
        return cur.lastrowid

    def review(self, candidate_id, reviewer, decision, note=""):
        if not (reviewer or "").strip():
            raise ValueError("검토자 이름이 필요하다")
        if decision not in ("approved", "rejected"):
            raise ValueError("결정은 approved 또는 rejected")
        row = self._cand(candidate_id)
        if row["status"] != "candidate":
            raise ValueError(f"이미 {row['status']} 상태다")
        self.con.execute("UPDATE material_candidates SET status=?,reviewer=?,review_note=?,reviewed_at=? WHERE candidate_id=?",
                         (decision, reviewer.strip(), note, time.time(), candidate_id))
        self.con.commit()

    def register(self, candidate_id):
        """승인된 후보만 등록한다. 같은 물질이면 기존 Material ID 로 연결한다. -> (material_id, 신규 여부)"""
        c = self._cand(candidate_id)
        if c["status"] == "registered":
            raise ValueError("이미 등록된 후보다")
        if c["status"] != "approved":
            raise ValueError("연구자가 승인한 후보만 등록할 수 있다")
        existing = self._find(c["cas"], c["smiles"], c["name"])
        if existing:
            mid, new = existing, False
            old = self.con.execute("SELECT material_class FROM materials WHERE material_id=?", (mid,)).fetchone()[0]
            if old != c["proposed_class"]:
                raise ValueError(f"기존 {mid} 는 {old} 로 등록돼 있다. 구분이 다르면 연구자가 먼저 정리한다")
        else:
            n = self.con.execute("SELECT count(*) FROM materials").fetchone()[0] + 1
            mid, new = f"MAT-{n:06d}", True
            self.con.execute("INSERT INTO materials VALUES (?,?,?,?,?,?,?)",
                             (mid, c["name"], c["proposed_class"], c["cas"], c["smiles"], candidate_id, time.time()))
        self.con.execute("INSERT OR IGNORE INTO material_aliases VALUES (?,?,?)", (norm(c["name"]), mid, c["name"]))
        self.con.execute("INSERT INTO material_sources(material_id,source_doi,role_in_source,source_quote) VALUES (?,?,?,?)",
                         (mid, c["source_doi"], c["role_in_source"], c["source_quote"]))
        self.con.execute("UPDATE material_candidates SET status='registered' WHERE candidate_id=?", (candidate_id,))
        self.con.commit()
        return mid, new

    # ---- 조회: 조성 입력과 DFT 가 같은 ID 를 쓰도록
    def resolve(self, name):
        r = self.con.execute("SELECT material_id FROM material_aliases WHERE alias_norm=?", (norm(name),)).fetchone()
        return r[0] if r else None

    def add_alias(self, material_id, alias):
        """약어·사내 표기(예: FEC)를 같은 Material ID 에 연결한다. 다른 물질의 별칭과 충돌하면 거부한다."""
        self.get(material_id)
        cur = self.resolve(alias)
        if cur and cur != material_id:
            raise ValueError(f"'{alias}' 는 이미 {cur} 의 이름이다")
        self.con.execute("INSERT OR IGNORE INTO material_aliases VALUES (?,?,?)", (norm(alias), material_id, alias))
        self.con.commit()

    def get(self, material_id):
        r = self.con.execute("SELECT * FROM materials WHERE material_id=?", (material_id,)).fetchone()
        if not r:
            raise KeyError(material_id)
        d = dict(r)
        d["sources"] = [dict(x) for x in self.con.execute("SELECT source_doi,role_in_source,source_quote FROM material_sources WHERE material_id=?", (material_id,))]
        return d

    def allowed_names(self):
        """composition.Rules.allowed_names 에 넣을 수 있는 {구분: [이름]} (등록된 물질만)."""
        out = {c: [] for c in CLASSES}
        for r in self.con.execute("SELECT material_class,name FROM materials ORDER BY material_id"):
            out[r[0]].append(r[1])
        return out

    def component_for(self, name, amount, unit, basis="total_electrolyte"):
        """조성 입력용 성분 행. 등록되지 않은 이름은 거부한다(조용히 새 물질을 만들지 않는다)."""
        mid = self.resolve(name)
        if mid is None:
            raise KeyError(f"{name}: 등록된 Material ID 가 없다. 문헌 후보 검토·등록을 먼저 한다")
        m = self.get(mid)
        return dict(component_class=m["material_class"], name=m["name"], amount=amount, unit=unit, basis=basis, material_id=mid)

    def dft_input(self, material_id, charge, multiplicity, method):
        """DFT 입력 명세. 계산은 하지 않는다. 필수 조건이 없으면 만들지 않는다."""
        m = self.get(material_id)
        missing = [k for k, v in (("SMILES(구조)", m["smiles"]), ("전하", charge), ("스핀다중도", multiplicity), ("방법", method)) if v in (None, "")]
        if missing:
            raise ValueError("DFT 입력을 만들 수 없다. 필요: " + ", ".join(missing))
        return dict(material_id=material_id, name=m["name"], structure={"smiles": m["smiles"]}, charge=charge,
                    multiplicity=multiplicity, method=method, provenance=m["sources"],
                    status="input_only_not_run", note="입력 명세만 생성했다. 계산 실행·수렴·정확도는 별도로 검증한다.")

    def export_rows(self):
        """사내 허브로 가져갈 등록 물질 행(공개 문헌 근거). 가져오는 절차는 사내가 정한다."""
        return [self.get(r[0]) for r in self.con.execute("SELECT material_id FROM materials ORDER BY material_id")]

    def _cand(self, cid):
        r = self.con.execute("SELECT * FROM material_candidates WHERE candidate_id=?", (cid,)).fetchone()
        if not r:
            raise KeyError(f"후보 {cid} 없음")
        return r

    def _find(self, cas, smiles, name):
        for col, val in (("cas", cas), ("smiles", smiles)):
            if val:
                r = self.con.execute(f"SELECT material_id FROM materials WHERE {col}=?", (val,)).fetchone()
                if r:
                    return r[0]
        return self.resolve(name)
