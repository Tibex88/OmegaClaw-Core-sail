import pytest


@pytest.fixture(scope="session")
def anyio_backend():
    return "asyncio"


def pytest_collection_modifyitems(config, items):
    for item in items:
        if "asyncio" in item.keywords and item.get_closest_marker("asyncio") is None:
            item.add_marker(pytest.mark.asyncio)
