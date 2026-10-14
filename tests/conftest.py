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


@pytest.fixture(autouse=True)
def _no_edr_spacing(monkeypatch):
    """The pause between DMI forecast API requests is real time; not in tests."""
    from custom_components.dmi_vejr import coordinator

    monkeypatch.setattr(coordinator, "EDR_SPACING_S", 0)
    monkeypatch.setattr(coordinator, "EDR_BUSY_RETRY_S", (0, 0))
    yield
