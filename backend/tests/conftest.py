import pytest

from fintea.providers import load_dataset


@pytest.fixture(scope="session", params=["MSFT", "AAPL", "NVDA"])
def dataset(request):
    return load_dataset(request.param, "sample")
