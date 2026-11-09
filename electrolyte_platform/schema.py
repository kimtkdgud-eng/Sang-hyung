"""공통 데이터 모델 (SQLite).

귀속 원칙:
  혼합 전해액 실측값 -> batch (제조 배치)
  순물질 물성        -> material (Material ID)   [다음 단계에서 확장]
  셀 평가            -> batch + 평가 조건
모든 행은 source(원본 추적)를 가진다. 누락값은 NULL로 두고 0으로 채우지 않는다.
"""
import sqlite3

DDL = """
CREATE TABLE IF NOT EXISTS material (
    material_id TEXT PRIMARY KEY,
    name        TEXT NOT NULL,
    role        TEXT NOT NULL CHECK (role IN ('salt','solvent','additive')),
    source      TEXT
);
CREATE TABLE IF NOT EXISTS composition (
    composition_id TEXT NOT NULL,
    version        INTEGER NOT NULL,
    source         TEXT,
    PRIMARY KEY (composition_id, version)
);
CREATE TABLE IF NOT EXISTS composition_item (
    composition_id TEXT NOT NULL,
    version        INTEGER NOT NULL,
    material_id    TEXT NOT NULL REFERENCES material(material_id),
    amount         REAL NOT NULL,
    unit           TEXT NOT NULL,            -- 'wt%' | 'vol%' | 'mol/L'
    FOREIGN KEY (composition_id, version) REFERENCES composition(composition_id, version)
);
CREATE TABLE IF NOT EXISTS batch (
    batch_id       TEXT PRIMARY KEY,
    composition_id TEXT NOT NULL,
    version        INTEGER NOT NULL,
    made_on        TEXT,
    source         TEXT,
    FOREIGN KEY (composition_id, version) REFERENCES composition(composition_id, version)
);
CREATE TABLE IF NOT EXISTS property_measurement (
    row_id      INTEGER PRIMARY KEY AUTOINCREMENT,
    batch_id    TEXT,                         -- NULL 허용: 누락은 제외 사유로 집계
    property    TEXT NOT NULL,                -- conductivity | viscosity | density
    value       REAL,
    unit        TEXT,
    temp_c      REAL,
    method      TEXT,
    source      TEXT
);
CREATE TABLE IF NOT EXISTS cell_result (
    row_id      INTEGER PRIMARY KEY AUTOINCREMENT,
    cell_id     TEXT NOT NULL,
    batch_id    TEXT,                         -- NULL 허용
    metric      TEXT NOT NULL,
    value       REAL,
    unit        TEXT,
    cell_spec   TEXT,
    temp_c      REAL,
    soc_pct     REAL,
    protocol    TEXT,
    extra       TEXT,                         -- 저장시간, 사이클 수, 펄스 조건 등
    source      TEXT
);
"""


def connect(path=":memory:"):
    con = sqlite3.connect(path)
    con.row_factory = sqlite3.Row
    con.executescript(DDL)
    return con
