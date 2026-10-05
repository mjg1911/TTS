"""Windows global hotkey registration and message dispatch."""

import ctypes
import queue
import threading
from typing import Any, Callable, Optional, Set, Tuple

from . import DEFAULT_PAUSE_RESUME_HOTKEY, DEFAULT_STOP_TTS_HOTKEY
from .hotkey import MOD_NOREPEAT, parse_hotkey


CAPTURE_IDS = (1, 3)
CANCEL_ID = 2
STOP_ID = CANCEL_ID
PAUSE_RESUME_ID = 4
HOTKEY_IDS = CAPTURE_IDS + (STOP_ID, PAUSE_RESUME_ID)
WM_HOTKEY = 0x0312
WM_QUIT = 0x0012
WM_COMMAND = 0x8001
PM_NOREMOVE = 0x0000

Callback = Callable[[], None]


class HotkeyRegistrationError(OSError):
    def __init__(self, message: str, role: str) -> None:
        super().__init__(message)
        self.role = role


class _MSG(ctypes.Structure):
    _fields_ = [
        ("hwnd", ctypes.c_void_p),
        ("message", ctypes.c_uint),
        ("wparam", ctypes.c_size_t),
        ("lparam", ctypes.c_ssize_t),
        ("time", ctypes.c_uint),
        ("pt_x", ctypes.c_long),
        ("pt_y", ctypes.c_long),
    ]


class _MessageCommand:
    def __init__(self, callback: Callable[[], Any]) -> None:
        self.callback = callback
        self.completed = threading.Event()
        self.result = None
        self.error: Optional[BaseException] = None


class _Win32HotkeyApi:
    """Small lazily-loaded user32 adapter used by the production manager."""

    def __init__(self) -> None:
        self._user32 = None

    def _load_user32(self) -> Any:
        if self._user32 is None:
            self._user32 = ctypes.WinDLL("user32", use_last_error=True)
            self._user32.RegisterHotKey.argtypes = [
                ctypes.c_void_p,
                ctypes.c_int,
                ctypes.c_uint,
                ctypes.c_uint,
            ]
            self._user32.RegisterHotKey.restype = ctypes.c_int
            self._user32.UnregisterHotKey.argtypes = [ctypes.c_void_p, ctypes.c_int]
            self._user32.UnregisterHotKey.restype = ctypes.c_int
            self._user32.GetMessageW.argtypes = [
                ctypes.c_void_p,
                ctypes.c_void_p,
                ctypes.c_uint,
                ctypes.c_uint,
            ]
            self._user32.GetMessageW.restype = ctypes.c_int
            self._user32.PeekMessageW.argtypes = [
                ctypes.c_void_p,
                ctypes.c_void_p,
                ctypes.c_uint,
                ctypes.c_uint,
                ctypes.c_uint,
            ]
            self._user32.PeekMessageW.restype = ctypes.c_int
            self._user32.PostThreadMessageW.argtypes = [
                ctypes.c_uint,
                ctypes.c_uint,
                ctypes.c_size_t,
                ctypes.c_ssize_t,
            ]
            self._user32.PostThreadMessageW.restype = ctypes.c_int
        return self._user32

    def register(self, hotkey_id: int, modifiers: int, vk: int) -> bool:
        return bool(self._load_user32().RegisterHotKey(None, hotkey_id, modifiers, vk))

    def unregister(self, hotkey_id: int) -> None:
        self._load_user32().UnregisterHotKey(None, hotkey_id)

    def get_message(self) -> Tuple[int, int, int]:
        msg = _MSG()
        result = self._load_user32().GetMessageW(ctypes.byref(msg), None, 0, 0)
        return result, int(msg.message), int(msg.wparam)

    def ensure_message_queue(self) -> None:
        msg = _MSG()
        self._load_user32().PeekMessageW(ctypes.byref(msg), None, 0, 0, PM_NOREMOVE)

    def post_quit(self, thread_id: int) -> bool:
        return bool(self._load_user32().PostThreadMessageW(thread_id, WM_QUIT, 0, 0))

    def post_command(self, thread_id: int) -> bool:
        return bool(self._load_user32().PostThreadMessageW(thread_id, WM_COMMAND, 0, 0))


class HotkeyManager:
    def __init__(self, api: Optional[Any] = None) -> None:
        self._api = api if api is not None else _Win32HotkeyApi()
        self._active_capture_id = CAPTURE_IDS[0]
        self.capture_spec = None
        self.stop_spec = None
        self.pause_resume_spec = None
        self._on_capture: Optional[Callback] = None
        self._on_cancel: Optional[Callback] = None
        self._on_stop: Optional[Callback] = None
        self._on_pause_resume: Optional[Callback] = None
        self._on_failure: Optional[Callable[[BaseException], None]] = None
        self._message_thread: Optional[threading.Thread] = None
        self._message_thread_id = 0
        self._ready = threading.Event()
        self._registration_error: Optional[BaseException] = None
        self.last_registration_error: Optional[BaseException] = None
        self._cancel_registered = False
        self._pause_registered = False
        self._owned_registrations = set()  # type: Set[int]
        self._pending_specs = None
        self._previous_specs = None
        self._pending_capture_id: Optional[int] = None
        self._capture_suspended = False
        self._lock = threading.RLock()
        self._commands = queue.Queue()
        self._direct_test_mode = False

    def _default_playback_specs(self) -> tuple[Any, Any]:
        return (
            parse_hotkey(DEFAULT_STOP_TTS_HOTKEY, allow_f8=True),
            parse_hotkey(DEFAULT_PAUSE_RESUME_HOTKEY),
        )

    def _register_spec_set(
        self,
        specs: tuple[Any, Any, Any],
        *,
        update_specs: bool,
        capture_id: Optional[int] = None,
    ) -> None:
        capture_spec, stop_spec, pause_resume_spec = specs
        capture_id = self._active_capture_id if capture_id is None else capture_id
        registrations = (
            (capture_id, capture_spec, "capture", "capture"),
            (STOP_ID, stop_spec, "stop", "stop"),
            (PAUSE_RESUME_ID, pause_resume_spec, "pause/resume", "pause_resume"),
        )
        registered = []
        try:
            for hotkey_id, spec, label, role in registrations:
                try:
                    success = self._api.register(
                        hotkey_id, spec.modifiers | MOD_NOREPEAT, spec.vk
                    )
                except OSError as error:
                    registration_error = HotkeyRegistrationError(
                        "%s hotkey registration failed" % label, role
                    )
                    self.last_registration_error = registration_error
                    raise registration_error from error
                if not success:
                    registration_error = HotkeyRegistrationError(
                        "%s hotkey registration failed" % label, role
                    )
                    self.last_registration_error = registration_error
                    raise registration_error
                registered.append(hotkey_id)
                self._owned_registrations.add(hotkey_id)
        except BaseException:
            for hotkey_id in reversed(registered):
                try:
                    self._api.unregister(hotkey_id)
                except BaseException:
                    continue
                self._owned_registrations.discard(hotkey_id)
            raise

        self._cancel_registered = True
        self._pause_registered = True
        self.last_registration_error = None
        if update_specs:
            self._active_capture_id = capture_id
            self.capture_spec, self.stop_spec, self.pause_resume_spec = specs

    def _unregister_spec_set(self) -> None:
        first_error = None
        for hotkey_id in HOTKEY_IDS:
            if hotkey_id not in self._owned_registrations:
                continue
            try:
                self._api.unregister(hotkey_id)
            except BaseException as error:
                if first_error is None:
                    first_error = error
            else:
                self._owned_registrations.discard(hotkey_id)
        self._cancel_registered = CANCEL_ID in self._owned_registrations
        self._pause_registered = PAUSE_RESUME_ID in self._owned_registrations
        if first_error is not None:
            raise first_error

    def _register_capture_set(
        self,
        capture_spec: Any,
        stop_spec: Any = None,
        pause_resume_spec: Any = None,
    ) -> None:
        default_stop, default_pause = self._default_playback_specs()
        specs = (
            capture_spec,
            stop_spec if stop_spec is not None else default_stop,
            pause_resume_spec if pause_resume_spec is not None else default_pause,
        )
        with self._lock:
            self._register_spec_set(specs, update_specs=True)

    def register_for_test(
        self,
        capture_spec: Any,
        stop_spec: Any = None,
        pause_resume_spec: Any = None,
    ) -> None:
        self._direct_test_mode = True
        self._register_capture_set(capture_spec, stop_spec, pause_resume_spec)

    def set_failure_callback(
        self, on_failure: Optional[Callable[[BaseException], None]]
    ) -> None:
        self._on_failure = on_failure

    def _notify_failure(self, error: BaseException) -> None:
        callback = self._on_failure
        if callback is not None:
            try:
                callback(error)
            except BaseException:
                pass

    def rebind(self, candidate: Any) -> bool:
        if not self.prepare_rebind(candidate):
            return False
        if self.commit_rebind():
            return True
        self.rollback_rebind()
        return False

    def prepare_rebind(
        self,
        candidate: Any,
        stop_candidate: Any = None,
        pause_resume_candidate: Any = None,
    ) -> bool:
        self.last_registration_error = None

        def command() -> bool:
            with self._lock:
                if (
                    self._capture_suspended
                    or self.capture_spec is None
                    or self.stop_spec is None
                    or self.pause_resume_spec is None
                    or self._pending_specs is not None
                ):
                    return False
                previous = (
                    self.capture_spec,
                    self.stop_spec,
                    self.pause_resume_spec,
                )
                candidate_specs = (
                    candidate,
                    stop_candidate if stop_candidate is not None else previous[1],
                    (
                        pause_resume_candidate
                        if pause_resume_candidate is not None
                        else previous[2]
                    ),
                )
                candidate_capture_id = (
                    CAPTURE_IDS[1]
                    if self._active_capture_id == CAPTURE_IDS[0]
                    else CAPTURE_IDS[0]
                )
                try:
                    self._unregister_spec_set()
                    self._register_spec_set(
                        candidate_specs,
                        update_specs=False,
                        capture_id=candidate_capture_id,
                    )
                except OSError:
                    registration_error = self.last_registration_error
                    if registration_error is None:
                        registration_error = HotkeyRegistrationError(
                            "hotkey registrations could not be updated",
                            "recovery",
                        )
                    try:
                        self._unregister_spec_set()
                        self._register_spec_set(previous, update_specs=False)
                    except BaseException as restore_error:
                        self._notify_failure(restore_error)
                        recovery_error = HotkeyRegistrationError(
                            "previous hotkey bindings could not be restored",
                            "recovery",
                        )
                        self.last_registration_error = recovery_error
                        raise recovery_error from restore_error
                    self.last_registration_error = registration_error
                    return False
                self._previous_specs = previous
                self._pending_specs = candidate_specs
                self._pending_capture_id = candidate_capture_id
                return True

        try:
            if self._message_thread_is_running():
                return bool(self._run_on_message_thread(command))
            if self._direct_test_mode:
                return bool(command())
            return False
        except OSError:
            return False

    def commit_rebind(self) -> bool:
        def command() -> bool:
            with self._lock:
                pending_specs = self._pending_specs
                pending_capture_id = self._pending_capture_id
                if pending_specs is None or pending_capture_id is None:
                    return False
                self._active_capture_id = pending_capture_id
                (
                    self.capture_spec,
                    self.stop_spec,
                    self.pause_resume_spec,
                ) = pending_specs
                self._pending_specs = None
                self._previous_specs = None
                self._pending_capture_id = None
                return True

        try:
            if self._message_thread_is_running():
                return bool(self._run_on_message_thread(command))
            if self._direct_test_mode:
                return bool(command())
            return False
        except OSError:
            return False

    def rollback_rebind(self) -> bool:
        def command() -> bool:
            with self._lock:
                if self._pending_specs is None:
                    return True
                previous = self._previous_specs
                if previous is None:
                    return False
                try:
                    self._unregister_spec_set()
                    self._register_spec_set(previous, update_specs=False)
                except BaseException as error:
                    self._notify_failure(error)
                    return False
                self._pending_specs = None
                self._previous_specs = None
                self._pending_capture_id = None
                return True

        try:
            if self._message_thread_is_running():
                return bool(self._run_on_message_thread(command))
            if self._direct_test_mode:
                return bool(command())
            return False
        except OSError:
            return False

    def reregister(self) -> bool:
        def command() -> bool:
            with self._lock:
                pending = self._pending_specs
                pending_capture_id = self._pending_capture_id
                specs = pending or (
                    self.capture_spec,
                    self.stop_spec,
                    self.pause_resume_spec,
                )
                if any(spec is None for spec in specs):
                    return False
                try:
                    self._unregister_spec_set()
                except OSError as error:
                    self._notify_failure(error)
                    return False
                if self._capture_suspended:
                    return True
                try:
                    self._register_spec_set(
                        specs,
                        update_specs=False,
                        capture_id=pending_capture_id,
                    )
                except OSError as error:
                    self._notify_failure(error)
                    return False
                return True

        try:
            if self._message_thread_is_running():
                return bool(self._run_on_message_thread(command))
            if self._direct_test_mode:
                return bool(command())
            return False
        except OSError:
            return False

    def suspend_capture(self) -> bool:
        """Temporarily unregister all application shortcuts while recording."""

        def command() -> bool:
            with self._lock:
                if self._capture_suspended:
                    return True
                if (
                    self.capture_spec is None
                    or self.stop_spec is None
                    or self.pause_resume_spec is None
                ):
                    return False
                try:
                    self._unregister_spec_set()
                except OSError as error:
                    self._notify_failure(error)
                    return False
                self._capture_suspended = True
                return True

        try:
            if self._message_thread_is_running():
                return bool(self._run_on_message_thread(command))
            if self._direct_test_mode:
                return bool(command())
            return False
        except OSError as error:
            self._notify_failure(error)
            return False

    def resume_capture(self) -> bool:
        """Restore the saved capture hotkey after shortcut recording."""

        def command() -> bool:
            with self._lock:
                if not self._capture_suspended:
                    return self.capture_spec is not None
                if (
                    self.capture_spec is None
                    or self.stop_spec is None
                    or self.pause_resume_spec is None
                ):
                    return False
                try:
                    self._register_spec_set(
                        (
                            self.capture_spec,
                            self.stop_spec,
                            self.pause_resume_spec,
                        ),
                        update_specs=False,
                    )
                except OSError as error:
                    self._notify_failure(error)
                    return False
                self._capture_suspended = False
                return True

        try:
            if self._message_thread_is_running():
                return bool(self._run_on_message_thread(command))
            if self._direct_test_mode:
                return bool(command())
            return False
        except OSError as error:
            self._notify_failure(error)
            return False

    def dispatch_message(
        self,
        message: int,
        hotkey_id: int,
        on_capture: Optional[Callback] = None,
        on_cancel: Optional[Callback] = None,
        on_pause_resume: Optional[Callback] = None,
    ) -> bool:
        if message == WM_QUIT:
            return False
        if message != WM_HOTKEY:
            return True
        capture = on_capture if on_capture is not None else self._on_capture
        stop = on_cancel if on_cancel is not None else self._on_stop
        pause_resume = (
            on_pause_resume
            if on_pause_resume is not None
            else self._on_pause_resume
        )
        with self._lock:
            # Registrations are swapped before settings persistence completes.
            # Ignore queued hotkey messages until commit or rollback so a
            # candidate playback shortcut cannot affect speech if saving fails.
            if self._capture_suspended or self._pending_specs is not None:
                return True
            active_capture_id = self._active_capture_id
        if hotkey_id in CAPTURE_IDS and hotkey_id == active_capture_id:
            if capture is not None:
                capture()
        elif hotkey_id == STOP_ID and stop is not None:
            stop()
        elif hotkey_id == PAUSE_RESUME_ID and pause_resume is not None:
            pause_resume()
        return True

    def _message_thread_is_running(self) -> bool:
        thread = self._message_thread
        return thread is not None and thread.is_alive()

    def _run_on_message_thread(self, callback: Callable[[], Any]) -> Any:
        thread = self._message_thread
        if thread is None or not thread.is_alive():
            raise OSError("hotkey message thread is unavailable")
        if threading.get_ident() == thread.ident:
            return callback()
        command = _MessageCommand(callback)
        self._commands.put(command)
        if not self._api.post_command(self._message_thread_id):
            raise OSError("failed to wake hotkey message thread")
        if not command.completed.wait(timeout=1.0):
            raise OSError("hotkey message thread did not complete command")
        if command.error is not None:
            raise command.error
        return command.result

    def _message_loop(self) -> None:
        self._message_thread_id = threading.get_native_id()
        with self._lock:
            specs = (
                self.capture_spec,
                self.stop_spec,
                self.pause_resume_spec,
            )
            self.capture_spec = None
            self.stop_spec = None
            self.pause_resume_spec = None
        try:
            try:
                self._api.ensure_message_queue()
                self._register_capture_set(*specs)
            except BaseException as exc:
                self._registration_error = exc
                self._ready.set()
                return
            self._ready.set()
            while True:
                result, message, hotkey_id = self._api.get_message()
                if result == 0:
                    return
                if result < 0:
                    self._notify_failure(
                        OSError("GetMessageW returned %d" % result)
                    )
                    return
                if message == WM_COMMAND:
                    command = self._commands.get()
                    try:
                        command.result = command.callback()
                    except BaseException as exc:
                        command.error = exc
                    finally:
                        command.completed.set()
                elif not self.dispatch_message(message, hotkey_id):
                    return
        except BaseException as error:
            self._notify_failure(error)
        finally:
            self._cleanup_owned_registrations()

    def _cleanup_owned_registrations(self) -> None:
        with self._lock:
            owned = tuple(
                hotkey_id
                for hotkey_id in HOTKEY_IDS
                if hotkey_id in self._owned_registrations
            )
            self._owned_registrations.clear()
            self._cancel_registered = False
            self._pause_registered = False
            self._capture_suspended = False
            self.capture_spec = None
            self.stop_spec = None
            self.pause_resume_spec = None
            self._pending_specs = None
            self._previous_specs = None
            self._pending_capture_id = None
        first_error = None
        for hotkey_id in owned:
            try:
                self._api.unregister(hotkey_id)
            except BaseException as error:
                if first_error is None:
                    first_error = error
        if first_error is not None:
            raise first_error

    def start(
        self,
        capture_spec: Any,
        on_capture: Callback,
        on_cancel: Optional[Callback] = None,
        *,
        stop_spec: Any = None,
        pause_resume_spec: Any = None,
        on_stop: Optional[Callback] = None,
        on_pause_resume: Optional[Callback] = None,
    ) -> None:
        default_stop, default_pause = self._default_playback_specs()
        stop_callback = on_stop if on_stop is not None else on_cancel
        if stop_callback is None:
            raise ValueError("a stop callback is required")
        specs = (
            capture_spec,
            stop_spec if stop_spec is not None else default_stop,
            (
                pause_resume_spec
                if pause_resume_spec is not None
                else default_pause
            ),
        )
        with self._lock:
            if self._message_thread is not None and self._message_thread.is_alive():
                self._on_capture = on_capture
                self._on_cancel = stop_callback
                self._on_stop = stop_callback
                self._on_pause_resume = on_pause_resume
                return
            (
                self.capture_spec,
                self.stop_spec,
                self.pause_resume_spec,
            ) = specs
            self._on_capture = on_capture
            self._on_cancel = stop_callback
            self._on_stop = stop_callback
            self._on_pause_resume = on_pause_resume
            self._ready.clear()
            self._registration_error = None
            self._direct_test_mode = False
            self._message_thread = threading.Thread(
                target=self._message_loop, name="piper-hotkeys", daemon=True
            )
            self._message_thread.start()
        self._ready.wait()
        if self._registration_error is not None:
            error = self._registration_error
            self._message_thread.join(timeout=1.0)
            self._message_thread = None
            self.capture_spec = None
            self.stop_spec = None
            self.pause_resume_spec = None
            raise error

    def stop(self) -> None:
        def command() -> None:
            with self._lock:
                self._unregister_spec_set()
                self._pending_specs = None
                self._previous_specs = None
                self._capture_suspended = False
                self.capture_spec = None
                self.stop_spec = None
                self.pause_resume_spec = None

        thread = self._message_thread
        if thread is not None and thread.is_alive():
            self._run_on_message_thread(command)
            if not self._api.post_quit(self._message_thread_id):
                raise OSError("failed to stop hotkey message thread")
        elif self._direct_test_mode:
            command()
        elif thread is not None:
            with self._lock:
                self._message_thread = None
                self.capture_spec = None
                self.stop_spec = None
                self.pause_resume_spec = None
            self._direct_test_mode = False
            return
        else:
            return
        if thread is not None and thread is not threading.current_thread():
            thread.join(timeout=1.0)
            if thread.is_alive():
                raise OSError("hotkey message thread did not stop")
        elif thread is threading.current_thread():
            raise OSError("cannot stop hotkey message thread from its owner thread")
        with self._lock:
            self._message_thread = None
            self._direct_test_mode = False
