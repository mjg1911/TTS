from piper.windows_tray.backend_manager import (
    BackendCandidate,
    BackendManager,
    BackendPreparationError,
)
from piper.windows_tray.controller import Controller
from piper.windows_tray.settings import TraySettings


class MatrixBackend:
    def __init__(self, name):
        self.name = name
        self.shutdown_calls = 0

    def shutdown(self):
        self.shutdown_calls += 1


class MatrixHotkeys:
    def prepare_rebind(self, _candidate):
        return True

    def commit_rebind(self):
        return True

    def rollback_rebind(self):
        return None


def _controller_with_kokoro_prepare_failure(reason, kokoro_voice_ids=("af_heart",)):
    piper = MatrixBackend("Piper")
    saved = []
    settings = TraySettings(
        engine="Piper",
        piper_voice="en_GB-alba-medium",
        kokoro_voice="af_heart",
    )

    def prepare_backend(engine, voice_id):
        if engine == "Kokoro":
            raise BackendPreparationError(reason)
        backend = MatrixBackend(engine)
        return BackendCandidate(engine, voice_id, backend, backend.shutdown)

    manager = BackendManager(piper, piper.shutdown, prepare_backend)
    controller = Controller(
        settings=settings,
        save_settings=saved.append,
        hotkeys=MatrixHotkeys(),
        backend_manager=manager,
        kokoro_voice_ids=kokoro_voice_ids,
    )
    return controller, manager, piper, saved


def _apply_kokoro(controller):
    settings = controller.state.settings
    return controller.apply_settings(
        "Kokoro",
        settings.hotkey,
        str(settings.pitch_percent),
        str(settings.speed_percent),
        None,
        "af_heart",
    )


def test_missing_payload_prepare_failure_keeps_piper_and_settings():
    controller, manager, piper, saved = _controller_with_kokoro_prepare_failure(
        "Kokoro is not installed"
    )
    before = controller.state.settings
    result = _apply_kokoro(controller)
    assert not result.applied
    assert result.error_map()["engine"] == "Kokoro is not available."
    assert manager.current() is piper
    assert controller.state.settings == before
    assert saved == []


def test_corrupt_manifest_prepare_failure_keeps_piper_and_settings():
    controller, manager, piper, saved = _controller_with_kokoro_prepare_failure(
        "Kokoro installation is invalid"
    )
    before = controller.state.settings
    result = _apply_kokoro(controller)
    assert not result.applied
    assert manager.current() is piper
    assert controller.state.settings == before
    assert saved == []


def test_handshake_failure_keeps_piper_and_settings():
    controller, manager, piper, saved = _controller_with_kokoro_prepare_failure(
        "Kokoro worker is incompatible"
    )
    before = controller.state.settings
    result = _apply_kokoro(controller)
    assert not result.applied
    assert manager.current() is piper
    assert controller.state.settings == before
    assert saved == []


def test_piper_settings_apply_when_kokoro_voice_list_is_empty():
    controller, manager, piper, saved = _controller_with_kokoro_prepare_failure(
        "Kokoro is not installed", kokoro_voice_ids=()
    )
    settings = controller.state.settings

    result = controller.apply_settings(
        "Piper",
        settings.hotkey,
        str(settings.pitch_percent),
        str(settings.speed_percent),
        None,
        settings.kokoro_voice,
    )

    assert result.applied
    assert manager.current().name == "Piper"
    assert piper.shutdown_calls == 1
    assert controller.state.settings.engine == "Piper"
    assert saved == [controller.state.settings]
