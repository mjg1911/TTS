from pathlib import Path

from piper.windows_tray.commands import Command, CommandKind
from piper.windows_tray.controller import CaptureCompletion, Controller, PlaybackState
from piper.windows_tray.speech import SpeechEvent, SpeechEventKind
from piper.windows_tray.voice_manager import VoiceManager
from piper.windows_tray.settings import TraySettings


class FakeSpeechWorker:
    def __init__(self):
        self.submitted = []
        self.cancelled = []

    def submit(self, request):
        self.submitted.append(request)

    def cancel_active(self, generation):
        self.cancelled.append(generation)


def test_no_text_replacement_notifies_without_submitting_speech():
    from piper.windows_tray.capture import CaptureResult, CaptureStatus

    jobs = []
    notifications = []
    worker = FakeSpeechWorker()
    controller = Controller(
        speech_worker=worker,
        capture=lambda: CaptureResult(CaptureStatus.EMPTY),
        capture_submit=jobs.append,
    )
    controller.configure_runtime(show_notification=notifications.append)
    controller.state.playback = PlaybackState.SPEAKING

    controller.handle(Command(CommandKind.CAPTURE_REQUEST))
    jobs[0]()
    completion = controller.drain_once()
    assert completion is not None
    controller.handle(completion)

    assert notifications == ["No text selected or the application did not provide it"]
    assert worker.submitted == []
    assert controller.state.playback is PlaybackState.STOPPED


def test_second_hotkey_plays_only_new_selection_and_ignores_stale_worker_event():
    from piper.windows_tray.capture import CaptureResult, CaptureStatus

    jobs = []
    worker = FakeSpeechWorker()
    results = iter(
        [
            CaptureResult(CaptureStatus.SUCCESS, "first"),
            CaptureResult(CaptureStatus.SUCCESS, "second"),
        ]
    )
    controller = Controller(
        speech_worker=worker,
        capture=lambda: next(results),
        capture_submit=jobs.append,
    )

    controller.handle(Command(CommandKind.CAPTURE_REQUEST))
    jobs.pop()()
    controller.handle(controller.drain_once())
    first_generation = controller.state.speech_generation

    controller.handle(Command(CommandKind.CAPTURE_REQUEST))
    jobs.pop()()
    controller.handle(controller.drain_once())

    controller.handle(
        Command(
            CommandKind.WORKER_EVENT,
            SpeechEvent(SpeechEventKind.FINISHED, first_generation),
        )
    )

    assert worker.cancelled == [first_generation]
    assert [request.text for request in worker.submitted] == ["first", "second"]
    assert controller.state.last_text == "second"
    assert controller.state.playback is PlaybackState.SPEAKING


def test_configure_voice_switches_synchronously_to_each_loaded_candidate():
    old_voice = object()
    new_voice = object()
    saved = []
    statuses = []
    controller = Controller(
        settings=TraySettings(voice="old.onnx"),
        save_settings=saved.append,
    )
    controller.set_voice(Path("old.onnx"), old_voice)
    controller.configure_runtime(
        choose_voice=lambda: Path("new.onnx"),
        load_voice=lambda _reference: (Path("new.onnx"), new_voice),
        show_status=statuses.append,
    )

    controller.handle(Command(CommandKind.CONFIGURE_VOICE))
    controller.handle(Command(CommandKind.CONFIGURE_VOICE))

    assert controller.state.voice_path == Path("new.onnx")
    assert controller.state.voice is new_voice
    assert len(saved) == 2
    assert statuses == []


def test_configure_voice_failure_reports_previous_voice_still_active():
    statuses = []
    controller = Controller(
        settings=TraySettings(voice="old.onnx"),
        save_settings=lambda _settings: None,
    )
    controller.set_voice(Path("old.onnx"), object())
    controller.configure_runtime(
        choose_voice=lambda: Path("bad.onnx"),
        load_voice=lambda _reference: (_ for _ in ()).throw(OSError("bad model")),
        show_status=statuses.append,
    )

    controller.handle(Command(CommandKind.CONFIGURE_VOICE))

    assert statuses == [
        "The selected voice could not be loaded. The previous voice is still active."
    ]


def test_app_speech_worker_reads_voice_manager_current_and_enqueues_events():
    import piper.windows_tray.app as app

    first_voice = object()
    second_voice = object()
    manager = VoiceManager(first_voice, lambda _reference: (Path("unused"), second_voice))
    controller = Controller()
    captured = {}

    class FakeWorker:
        def __init__(self, voice_provider, on_event, player_factory):
            captured.update(
                voice_provider=voice_provider,
                on_event=on_event,
                player_factory=player_factory,
            )

    original = app.SpeechWorker
    app.SpeechWorker = FakeWorker
    try:
        app._build_speech_worker(controller, manager)
    finally:
        app.SpeechWorker = original

    assert captured["voice_provider"]() is first_voice
    manager.replace(second_voice)
    assert captured["voice_provider"]() is second_voice
    captured["on_event"](SpeechEvent(SpeechEventKind.FINISHED, 4))
    assert controller.drain_once() == Command(
        CommandKind.WORKER_EVENT,
        SpeechEvent(SpeechEventKind.FINISHED, 4),
    )


def test_tray_stop_and_replay_actions_use_dynamic_enablement(monkeypatch, tmp_path):
    import piper.windows_tray.tray_icon as tray_icon

    class FakeItem:
        def __init__(self, text, action, enabled=None, checked=None):
            self.text = text
            self.action = action
            self.enabled = enabled
            self.checked = checked

    class FakePystray:
        MenuItem = FakeItem
        Menu = lambda *items: type("Menu", (), {"items": items})()

        class Icon:
            def __init__(self, _name, _image, _title, menu):
                self.menu = menu

            def run_detached(self):
                pass

    class ImageApi:
        @staticmethod
        def open(_path):
            return object()

    monkeypatch.setattr(tray_icon, "_load_dependencies", lambda: (FakePystray, ImageApi))
    commands = []
    snapshot = type("Snapshot", (), {"can_stop": False, "can_replay": False})()
    tray = tray_icon.TrayIcon(tmp_path / "icon.png", commands.append, lambda: snapshot)
    tray.start()

    items = {item.text: item for item in tray._icon.menu.items}
    assert items["Stop speaking"].enabled(items["Stop speaking"]) is False
    snapshot.can_stop = True
    snapshot.can_replay = True
    assert items["Stop speaking"].enabled(items["Stop speaking"]) is True
    assert items["Replay"].enabled(items["Replay"]) is True
    items["Stop speaking"].action(None, items["Stop speaking"])
    items["Replay"].action(None, items["Replay"])
    assert [command.kind for command in commands] == [
        CommandKind.STOP_REQUEST,
        CommandKind.REPLAY_REQUEST,
    ]
