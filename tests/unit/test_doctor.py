from document_enhancer.config import load_config
from document_enhancer.doctor import doctor_json, run_doctor


def test_doctor_reports_capabilities_without_credentials() -> None:
    checks = run_doctor(load_config(environ={}))
    payload = doctor_json(checks)
    by_name = {item["name"]: item for item in payload}
    assert by_name["sqlite_fts5"]["status"] == "pass"
    assert by_name["spike:sqlite_fts5_and_sqlite_vec"]["status"] == "pass"
    assert by_name["future_milestones"]["status"] == "info"
