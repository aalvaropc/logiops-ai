import pytest

from logiops.scenario import reset_registry


@pytest.fixture(autouse=True)
def clean_scenario_registry():
    reset_registry()
    yield
    reset_registry()
