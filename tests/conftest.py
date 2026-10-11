import pytest


@pytest.fixture(scope="session", autouse=True)
def _pycares_shutdown_thread():
    """pycares (aiodns) starts one daemon cleanup thread the first time a
    channel closes. Start it before the tests so HA's lingering-thread check
    does not blame whichever test first closes the web client session."""
    try:
        import pycares
    except ImportError:
        yield
        return
    pycares.Channel().close()
    yield


@pytest.fixture(autouse=True)
def auto_enable_custom_integrations(request):
    if "hass" in request.fixturenames:
        request.getfixturevalue("enable_custom_integrations")
    yield
