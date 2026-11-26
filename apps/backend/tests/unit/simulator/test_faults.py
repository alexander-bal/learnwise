import pytest

from app.simulator.faults import FaultIn, FaultStore


def test_faults_load_from_the_startup_config_in_order(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SIM_FAULTS", '[{"type": "5xx", "model": "fake"}, {"type": "reject"}]')
    store = FaultStore()
    store.load_env()

    assert [(f.type, f.model) for f in store.all()] == [("5xx", "fake"), ("reject", None)]
    assert [f.type for f in store.matching("fake-judge")] == ["reject"]


def test_a_removed_fault_is_gone_and_an_unknown_id_is_reported() -> None:
    store = FaultStore()
    fault = store.add(FaultIn(type="delay", seconds=1))
    assert store.remove(fault.id)
    assert not store.remove(fault.id)
    assert store.all() == []
