import pytest

from document_enhancer.compatibility import run_offline_spikes


@pytest.mark.integration
def test_offline_ecosystem_spikes_pass() -> None:
    results = run_offline_spikes()
    failures = {name: result for name, result in results.items() if result["status"] != "pass"}
    assert not failures, failures
