"""데모·시험용 스키마.

internal_recipes / internal_recipe_components / internal_results 는 v2.12 소스(feature_hub.py, routes.py, 시험 코드)의
사용 흔적에서 복원한 것이다(schema_v2.sql 은 발췌본에 없음). 실제 DB를 대체하지 않는다.
batches / batch_properties / internal_results.batch_id 는 사내 11/09 변경의 자리표시자이며 실제 이름과 다를 수 있다.
-> 사내에서는 adapters.DEFAULT_SQL 의 SELECT 문만 실제 테이블에 맞게 바꾼다.
"""
import sqlite3

DDL = """
CREATE TABLE IF NOT EXISTS internal_recipes(
    recipe_id TEXT PRIMARY KEY, label TEXT, notes TEXT, created_at REAL);
CREATE TABLE IF NOT EXISTS internal_recipe_components(
    id INTEGER PRIMARY KEY AUTOINCREMENT, recipe_id TEXT NOT NULL, name TEXT NOT NULL,
    component_class TEXT NOT NULL, amount REAL NOT NULL, unit TEXT NOT NULL, basis TEXT NOT NULL, material_id TEXT);
CREATE TABLE IF NOT EXISTS internal_results(
    id INTEGER PRIMARY KEY AUTOINCREMENT, recipe_id TEXT NOT NULL, test_id TEXT NOT NULL, metric TEXT NOT NULL,
    value REAL, unit TEXT, temperature_C REAL, condition_json TEXT, source_ref TEXT, created_at REAL,
    outcome TEXT NOT NULL DEFAULT 'observed', failure_tags TEXT NOT NULL DEFAULT '', replicate_group TEXT,
    data_quality REAL,
    batch_id TEXT);                                  -- 자리표시자(사내 11/09 변경)
CREATE TABLE IF NOT EXISTS batches(                  -- 자리표시자
    batch_id TEXT PRIMARY KEY, recipe_id TEXT NOT NULL, made_on TEXT, source TEXT);
CREATE TABLE IF NOT EXISTS batch_properties(         -- 자리표시자
    row_id INTEGER PRIMARY KEY AUTOINCREMENT, batch_id TEXT, property TEXT NOT NULL, value REAL, unit TEXT,
    temp_c REAL, method TEXT, source TEXT);
"""


def connect(path=":memory:"):
    con = sqlite3.connect(path)
    con.row_factory = sqlite3.Row
    con.executescript(DDL)
    return con
