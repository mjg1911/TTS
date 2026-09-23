import pytest

from piper.windows_tray.backend_manager import (
    BackendCandidate,
    BackendManager,
    BackendPreparationError,
)


class FakeBackend:
    def __init__(self):
        self.shutdown_calls = 0

    def shutdown(self):
        self.shutdown_calls += 1


def test_prepare_does_not_replace_current_backend():
    current = FakeBackend()
    prepared_backend = FakeBackend()
    manager = BackendManager(
        current,
        current.shutdown,
        lambda engine, voice: BackendCandidate(
            engine, voice, prepared_backend, prepared_backend.shutdown
        ),
    )
    candidate = manager.prepare("Kokoro", "af_heart")
    assert manager.current() is current
    assert candidate.backend is prepared_backend


def test_discard_closes_uncommitted_candidate_exactly_once():
    current = FakeBackend()
    prepared_backend = FakeBackend()
    manager = BackendManager(
        current,
        current.shutdown,
        lambda engine, voice: BackendCandidate(
            engine, voice, prepared_backend, prepared_backend.shutdown
        ),
    )
    candidate = manager.prepare("Kokoro", "af_heart")
    manager.discard(candidate)
    manager.discard(candidate)
    assert prepared_backend.shutdown_calls == 1
    assert manager.current() is current


def test_commit_transfers_candidate_ownership_and_closes_old_backend():
    current = FakeBackend()
    prepared_backend = FakeBackend()
    manager = BackendManager(
        current,
        current.shutdown,
        lambda engine, voice: BackendCandidate(
            engine, voice, prepared_backend, prepared_backend.shutdown
        ),
    )
    candidate = manager.prepare("Kokoro", "af_heart")
    manager.commit(candidate)
    assert manager.current() is prepared_backend
    assert current.shutdown_calls == 1
    assert prepared_backend.shutdown_calls == 0
    manager.discard(candidate)
    assert prepared_backend.shutdown_calls == 0


def test_commit_defers_closing_backend_until_lease_is_released():
    current = FakeBackend()
    prepared_backend = FakeBackend()
    manager = BackendManager(
        current,
        current.shutdown,
        lambda engine, voice: BackendCandidate(
            engine, voice, prepared_backend, prepared_backend.shutdown
        ),
    )
    leased_backend, release = manager.acquire()
    manager.commit(manager.prepare("Kokoro", "af_heart"))

    assert leased_backend is current
    assert current.shutdown_calls == 0
    release()
    assert current.shutdown_calls == 1


def test_shutdown_defers_closing_backend_until_lease_is_released():
    current = FakeBackend()
    manager = BackendManager(current, current.shutdown, lambda *_: None)
    _backend, release = manager.acquire()

    manager.shutdown()
    manager.shutdown()
    assert current.shutdown_calls == 0
    release()
    assert current.shutdown_calls == 1


def test_candidate_cannot_be_committed_after_discard():
    current = FakeBackend()
    prepared_backend = FakeBackend()
    manager = BackendManager(
        current,
        current.shutdown,
        lambda engine, voice: BackendCandidate(
            engine, voice, prepared_backend, prepared_backend.shutdown
        ),
    )
    candidate = manager.prepare("Kokoro", "af_heart")
    manager.discard(candidate)
    with pytest.raises(RuntimeError, match="candidate ownership already released"):
        manager.commit(candidate)


def test_shutdown_closes_active_backend_once():
    current = FakeBackend()
    manager = BackendManager(
        current,
        current.shutdown,
        lambda engine, voice: (_ for _ in ()).throw(
            BackendPreparationError("unused")
        ),
    )
    manager.shutdown()
    manager.shutdown()
    assert current.shutdown_calls == 1
