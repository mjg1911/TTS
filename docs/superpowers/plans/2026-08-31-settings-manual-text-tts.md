# Settings Manual Text-to-Speech Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use `superpowers:subagent-driven-development` to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the Settings window's latest captured text editable and add a button that speaks its current contents temporarily.

**Architecture:** Add a Settings-to-UI-to-controller callback. The controller submits nonblank manual text through the existing foreground `SpeechRequest` path, interrupting active foreground speech while leaving `state.last_text` unchanged. No settings model or persistence changes are needed.

**Tech Stack:** Python, Tkinter/ttk, pytest, existing `Controller`, `SpeechWorker`, and `SpeechRequest` abstractions.

## Global Constraints

- Manual edits are temporary and must not replace `state.last_text`.
- Empty or whitespace-only text must be a silent no-op.
- Manual speech uses the normal foreground speech path and existing voice, pitch, speed, cancellation, lifecycle, and error handling.
- Existing replay remains based on captured `state.last_text`.
- Do not add settings persistence or schema fields.
- Preserve unrelated working-tree changes.
- Do not push, create a pull request, or merge without explicit user approval.
- Use `superpowers:subagent-driven-development` for execution, with one fresh implementer subagent and a review subagent per task, followed by a whole-branch review.
- Use only `luna-medium` agents for every delegated implementation, task review, fix, and final whole-branch review.

---

## File Structure

- `src/piper/windows_tray/controller.py`: accepts the manual request and submits foreground speech.
- `src/piper/windows_tray/settings_window.py`: owns the editable widget and button.
- `src/piper/windows_tray/ui.py`: forwards the callback into the Settings window.
- `src/piper/windows_tray/app.py`: wires the controller method during startup.
- `tests/windows_tray/test_controller_speech.py`: controller speech-generation and guard tests.
- `tests/windows_tray/test_settings_window.py`: widget/button/callback tests and TkUi forwarding tests.
- `tests/windows_tray/test_app_foundation.py`: startup test double and callback wiring coverage.

### Task 1: Add controller manual-speech behavior

**Files:**
- Modify: `src/piper/windows_tray/controller.py` next to `_replay()`.
- Test: `tests/windows_tray/test_controller_speech.py`.

**Interfaces:**
- Consumes: `PlaybackState`, `SpeechWorker.cancel_active()`, and `SpeechWorker.submit(SpeechRequest)`.
- Produces: `Controller.speak_manual_text(text: str) -> None`.

- [ ] **Step 1: Write failing tests**

Add tests using the existing `FakeSpeechWorker`:

```python
def test_manual_text_speaks_without_replacing_last_text():
    worker = FakeSpeechWorker()
    controller = Controller(speech_worker=worker)
    controller.state.last_text = "captured"
    controller.speak_manual_text("edited\ntext")
    assert controller.state.last_text == "captured"
    assert controller.state.playback is PlaybackState.SPEAKING
    assert worker.submitted == [SpeechRequest(1, "edited\ntext")]


def test_manual_text_ignores_empty_or_whitespace_only_text():
    worker = FakeSpeechWorker()
    controller = Controller(speech_worker=worker)
    controller.state.playback = PlaybackState.SPEAKING
    controller.state.speech_generation = 4

    controller.speak_manual_text(" \n\t")

    assert controller.state.speech_generation == 4
    assert controller.state.playback is PlaybackState.SPEAKING
    assert worker.cancelled == []
    assert worker.submitted == []


def test_manual_text_interrupts_current_foreground_speech():
    worker = FakeSpeechWorker()
    controller = Controller(speech_worker=worker)
    controller.state.playback = PlaybackState.SPEAKING
    controller.state.speech_generation = 4
    controller.speak_manual_text("new text")
    assert worker.cancelled == [4]
    assert controller.state.speech_generation == 5
    assert controller.state.playback is PlaybackState.SPEAKING
    assert worker.submitted == [SpeechRequest(5, "new text")]


def test_manual_text_is_ignored_during_capture_or_shutdown():
    worker = FakeSpeechWorker()
    controller = Controller(speech_worker=worker)
    controller.state.capture_in_progress = True
    controller.speak_manual_text("ignored during capture")
    controller.state.capture_in_progress = False
    controller.state.shutting_down = True
    controller.speak_manual_text("ignored during shutdown")
    assert worker.submitted == []
    assert controller.state.speech_generation == 0
```

- [ ] **Step 2: Run `pytest tests/windows_tray/test_controller_speech.py -q`; confirm failure because `speak_manual_text` is undefined.**
- [ ] **Step 3: Implement next to `_replay()`, including the direct-call lock:**

```python
def speak_manual_text(self, text: str) -> None:
    with self._state_lock:
        if (
            self.state.shutting_down
            or self.state.capture_in_progress
            or not text.strip()
        ):
            return

        if self.state.playback is PlaybackState.SPEAKING:
            if self._speech_worker is not None:
                self._speech_worker.cancel_active(
                    self.state.speech_generation
                )

        self.state.speech_generation += 1
        self.state.playback = PlaybackState.SPEAKING

        if self._speech_worker is not None:
            self._speech_worker.submit(
                SpeechRequest(
                    self.state.speech_generation,
                    text,
                )
            )
```

Do not assign the text to `state.last_text`.
- [ ] **Step 4: Run `pytest tests/windows_tray/test_controller_speech.py -q`; confirm all tests pass.**
- [ ] **Step 5: Commit:** `git add -- src/piper/windows_tray/controller.py tests/windows_tray/test_controller_speech.py` followed by `git commit -m "feat: speak temporary settings text"`.

### Task 2: Make the Settings field editable and add the action

**Files:**
- Modify: `src/piper/windows_tray/settings_window.py`.
- Test: `tests/windows_tray/test_settings_window.py`.

**Interfaces:**
- Consumes: `on_speak_text: Callable[[str], None]`.
- Produces: editable `last_text` and a `Speak text` button.

- [ ] **Step 1: Write failing UI tests**

Update every existing `SettingsWindow(...)` construction in this test file with:

```python
on_speak_text=lambda _text: None,
```

Add these tests:

```python
def test_speak_text_forwards_exact_multiline_contents(monkeypatch):
    settings_window = install_fake_tk(monkeypatch, [])
    spoken = []
    window = settings_window.SettingsWindow(
        parent=object(),
        snapshot=make_snapshot(),
        on_apply=lambda *_args: SettingsApplyResult(True),
        on_speak_text=spoken.append,
        on_close=lambda: None,
    )

    window.last_text.delete("1.0", "end")
    window.last_text.insert("1.0", "replacement\ntext")
    window.speak_text_button.kwargs["command"]()

    assert spoken == ["replacement\ntext"]


def test_speak_text_ignores_whitespace_only_contents(monkeypatch):
    settings_window = install_fake_tk(monkeypatch, [])
    spoken = []
    window = settings_window.SettingsWindow(
        parent=object(),
        snapshot=make_snapshot(),
        on_apply=lambda *_args: SettingsApplyResult(True),
        on_speak_text=spoken.append,
        on_close=lambda: None,
    )

    window.last_text.delete("1.0", "end")
    window.last_text.insert("1.0", " \n\t")
    window.speak_text_button.kwargs["command"]()

    assert spoken == []


def test_last_text_is_editable_and_refreshes_after_capture(monkeypatch):
    settings_window = install_fake_tk(monkeypatch, [])
    window = settings_window.SettingsWindow(
        parent=object(),
        snapshot=make_snapshot(),
        on_apply=lambda *_args: SettingsApplyResult(True),
        on_speak_text=lambda _text: None,
        on_close=lambda: None,
    )

    assert window.last_text.configured["state"] == "normal"
    window.update_last_text("new capture")

    assert window.last_text.value == "new capture"
    assert window.last_text_value == "new capture"
    assert window.last_text.configured["state"] == "normal"
```

- [ ] **Step 2: Run `pytest tests/windows_tray/test_settings_window.py -q`; confirm failures for the missing callback/button and disabled widget.**
- [ ] **Step 3: Implement the constructor, editable widget, button, and callback:**

Change the constructor signature and callback storage to:

```python
def __init__(
    self,
    parent: tk.Misc,
    snapshot: SettingsWindowSnapshot,
    on_apply: Callable[[str, str, str, Optional[Path]], SettingsApplyResult],
    on_speak_text: Callable[[str], None],
    on_close: Callable[[], None],
) -> None:
    # existing window construction remains unchanged
    self._on_apply = on_apply
    self._on_speak_text = on_speak_text
    self._on_close = on_close
```

Build the text section as follows, keeping the existing frame/grid setup:

```python
self.last_text = tk.Text(text_frame, width=60, height=8, wrap="word")
self.last_text.grid(row=0, column=0, sticky="nsew", padx=6, pady=6)
self.speak_text_button = ttk.Button(
    text_frame,
    text="Speak text",
    command=self._speak_text,
)
self.speak_text_button.grid(row=1, column=0, sticky="e", padx=6, pady=(0, 6))
text_frame.columnconfigure(0, weight=1)
text_frame.rowconfigure(0, weight=1)
```

Implement the action and refresh method exactly as follows:

```python
def _speak_text(self) -> None:
    text = self.last_text.get("1.0", "end-1c")
    if text.strip():
        self._on_speak_text(text)


def update_last_text(self, text: Optional[str]) -> None:
    value = text or "No text has been captured yet."
    self.last_text_value = text
    self.last_text.configure(state="normal")
    self.last_text.delete("1.0", "end")
    self.last_text.insert("1.0", value)
    self.last_text.configure(state="normal")
```

The fallback remains intentional and speakable when `text is None`; retain the existing `last_text_value` meaning.

- [ ] **Step 4: Run `pytest tests/windows_tray/test_settings_window.py -q`; confirm all tests pass.**
- [ ] **Step 5: Commit:** `git add -- src/piper/windows_tray/settings_window.py tests/windows_tray/test_settings_window.py` followed by `git commit -m "feat: add editable settings speech field"`.

### Task 3: Wire the callback through TkUi and application startup

**Files:**
- Modify: `src/piper/windows_tray/ui.py` in `open_settings()`.
- Modify: `src/piper/windows_tray/app.py` in `configure_runtime()`.
- Modify: `tests/windows_tray/test_settings_window.py` and `tests/windows_tray/test_app_foundation.py` test doubles.

**Interfaces:**
- Consumes: `Controller.speak_manual_text(text: str) -> None`.
- Produces: `TkUi.open_settings(snapshot, on_apply, on_speak_text)` forwarding the callback.

- [ ] **Step 1: Write failing forwarding tests**

Make the existing `RecordingWindow` capture constructor kwargs and assert the callback is forwarded:

```python
callback = lambda _text: None
ui.open_settings(make_snapshot(), apply_callback, callback)
assert created[0]["on_speak_text"] is callback
```

Update `FakeUi` in `test_app_foundation.py` to retain and exercise the callback:

```python
class FakeUi:
    def __init__(self, events):
        self.events = events
        self.root = FakeRoot(events)
        self.statuses = []
        self.settings_apply = None
        self.settings_speak_text = None

    def open_settings(self, snapshot, on_apply, on_speak_text):
        self.events.append(("settings.open", snapshot))
        self.settings_apply = on_apply
        self.settings_speak_text = on_speak_text
```

In the existing primary bootstrap test, replace the real speech worker with the existing `RecordingSpeechWorker`, keep the controller reference, open Settings through the normal command pump, and invoke the stored callback:

```python
from piper.windows_tray.speech import SpeechRequest

worker = RecordingSpeechWorker(events, tray)
monkeypatch.setattr(
    app,
    "_build_speech_worker",
    lambda _controller, _voice_manager: worker,
)

controller_holder = []
original_controller = app.Controller
monkeypatch.setattr(
    app,
    "Controller",
    lambda *args, **kwargs: controller_holder.append(
        original_controller(*args, **kwargs)
    )
    or controller_holder[-1],
)

def mainloop():
    controller_holder[0].enqueue(Command(CommandKind.CONFIGURE_SETTINGS))
    ui.root.callbacks.pop(0)()
    ui.settings_speak_text("typed from Settings")

ui.root.mainloop = mainloop
assert app.run_app([]) == 0

assert worker.submitted[-1] == SpeechRequest(
    1,
    "typed from Settings",
)
```

Import `SpeechRequest` in the test file. This invocation proves the callback is usable through application startup; do not compare bound-method identities.

- [ ] **Step 2: Run `pytest tests/windows_tray/test_settings_window.py tests/windows_tray/test_app_foundation.py -q`; confirm callback-signature failures.**
- [ ] **Step 3: Implement the UI boundary and startup wiring:**

Use this signature and constructor forwarding in `TkUi`:

```python
def open_settings(
    self,
    snapshot: SettingsWindowSnapshot,
    on_apply,
    on_speak_text,
) -> None:
    self._assert_main_thread()
    current = self._settings_window
    if current is not None:
        current.focus()
        return

    def cleared() -> None:
        self._settings_window = None

    self._settings_window = SettingsWindow(
        parent=self.root,
        snapshot=snapshot,
        on_apply=on_apply,
        on_speak_text=on_speak_text,
        on_close=cleared,
    )
    self._settings_window.focus()
```

Use this startup callback in `app.py`:

```python
open_settings=lambda snapshot: ui.open_settings(
    snapshot,
    controller.apply_settings,
    controller.speak_manual_text,
),
```

Update all affected test calls and doubles to pass the third callback. Do not add a command or alter tray replay.
- [ ] **Step 4: Run `pytest tests/windows_tray/test_settings_window.py tests/windows_tray/test_app_foundation.py -q`; confirm all pass.**
- [ ] **Step 5: Commit:** `git add -- src/piper/windows_tray/ui.py src/piper/windows_tray/app.py tests/windows_tray/test_settings_window.py tests/windows_tray/test_app_foundation.py` followed by `git commit -m "feat: wire settings manual speech action"`.

### Task 4: Regression verification

**Files:** No source changes expected.

- [ ] **Step 1:** Run `pytest tests/windows_tray/test_settings_window.py tests/windows_tray/test_controller_speech.py tests/windows_tray/test_app_foundation.py -q`; expected PASS.
- [ ] **Step 2:** Run `pytest -q`; expected PASS with no capture, replay, speech, persistence, or lifecycle regressions.
- [ ] **Step 3:** Run `script\\lint`; expected successful completion.
- [ ] **Step 4:** Run `git diff main...HEAD --check` and `git status --short --branch`; confirm only planned feature files are in feature commits and unrelated pre-existing changes remain untouched. Do not push or create a pull request without approval.
- [ ] **Step 5:** Perform the Windows manual acceptance check: open Settings, replace the field with edited multiline text, click `Speak text`, verify the edited text is spoken, then click tray `Replay` and verify the captured `state.last_text` is spoken instead. Confirm the manual edit did not replace captured text.

## Self-review

- Spec coverage: edit/paste behavior, silent blank no-op, interruption, temporary state, capture refresh, lifecycle guards, error reuse, persistence exclusion, and testing are covered by Tasks 1–4.
- Placeholder scan: no `TBD`, `TODO`, or unspecified implementation step remains.
- Type consistency: the callback is consistently `Callable[[str], None]`, and the controller method is consistently `speak_manual_text(text: str) -> None`.

