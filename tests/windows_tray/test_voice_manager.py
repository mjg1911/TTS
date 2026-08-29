from pathlib import Path

from piper.windows_tray.commands import Command, CommandKind
from piper.windows_tray.controller import Controller, PlaybackState
from piper.windows_tray.settings import TraySettings
from piper.windows_tray.voice_manager import VoiceManager


class FakeLoader:
    def __init__(self):
        self.error = None
        self.calls = []

    def __call__(self, reference):
        self.calls.append(reference)
        if self.error is not None:
            raise self.error
        return Path(reference), "candidate"


def test_failed_candidate_load_keeps_current_voice() -> None:
    good = object()
    fake_loader = FakeLoader()
    manager = VoiceManager(good, fake_loader)
    fake_loader.error = ValueError("bad model")
    events = []

    manager.begin_switch("bad.onnx", 3, events.append)
    manager.join_for_test()

    assert manager.current() is good
    assert events[0].generation == 3
    assert events[0].success is False


def test_successful_candidate_load_emits_candidate_without_swapping() -> None:
    good = object()
    fake_loader = FakeLoader()
    manager = VoiceManager(good, fake_loader)
    events = []

    manager.begin_switch("good.onnx", 4, events.append)
    manager.join_for_test()

    assert manager.current() is good
    assert events[0].success is True
    assert events[0].model_path == Path("good.onnx")
    assert events[0].voice == "candidate"


def test_controller_stops_active_speech_before_starting_voice_switch() -> None:
    class FakeSpeechWorker:
        def __init__(self):
            self.cancelled = []

        def cancel_active(self, generation):
            self.cancelled.append(generation)

        def cancel_auxiliary(self):
            pass

    worker = FakeSpeechWorker()
    manager = VoiceManager(object(), FakeLoader())
    controller = Controller(
        speech_worker=worker,
        voice_manager=manager,
        settings=TraySettings(voice="old.onnx"),
        save_settings=lambda _settings: None,
    )
    controller.set_voice(Path("old.onnx"), object())
    controller.configure_runtime(
        choose_voice=lambda: Path("new.onnx"),
        load_voice=lambda reference: (Path(reference), "new voice"),
    )
    controller.state.playback = PlaybackState.SPEAKING
    controller.state.speech_generation = 8

    controller.handle(Command(CommandKind.CONFIGURE_VOICE))

    assert worker.cancelled == [8]
    assert controller.state.playback is PlaybackState.STOPPED
    assert controller.state.speech_generation == 9
