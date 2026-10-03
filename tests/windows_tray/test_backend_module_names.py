from importlib.util import find_spec


def test_shared_worker_utilities_are_available_under_backend_names():
    for name in (
        "piper.windows_tray.worker_protocol",
        "piper.windows_tray.worker_process",
        "piper.windows_tray.backend_startup",
    ):
        assert find_spec(name) is not None


def test_shared_worker_utilities_have_no_kokoro_named_modules():
    for name in (
        "piper.windows_tray.kokoro_protocol",
        "piper.windows_tray.kokoro_process",
        "piper.windows_tray.kokoro_startup",
    ):
        assert find_spec(name) is None
