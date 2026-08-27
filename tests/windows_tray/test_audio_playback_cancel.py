import threading
from unittest.mock import Mock

import pytest

from piper.audio_playback import AudioPlayer


def test_stop_terminates_active_player_once() -> None:
    process = Mock()
    process.poll.return_value = None
    player = AudioPlayer(22050)
    player._proc = process

    player.stop()
    player.stop()

    process.terminate.assert_called_once()


def test_exit_after_stop_does_not_try_to_write_or_double_terminate() -> None:
    process = Mock()
    process.poll.return_value = 0
    player = AudioPlayer(22050)
    player._proc = process

    player.stop()
    player.__exit__(None, None, None)
    assert process.terminate.call_count <= 1


def test_stop_can_terminate_while_play_is_blocked_in_stdin_write() -> None:
    write_started = threading.Event()
    release_write = threading.Event()
    write_stream = Mock()

    def blocked_write(audio_bytes: bytes) -> None:
        write_started.set()
        release_write.wait(timeout=2)

    write_stream.write.side_effect = blocked_write
    process = Mock()
    process.poll.return_value = None
    process.stdin = write_stream
    player = AudioPlayer(22050)
    player._proc = process

    play_thread = threading.Thread(target=player.play, args=(b"audio",))
    stop_finished = threading.Event()
    stop_thread = threading.Thread(
        target=lambda: (player.stop(), stop_finished.set())
    )
    play_thread.start()
    assert write_started.wait(timeout=1)
    stop_thread.start()

    try:
        assert stop_finished.wait(timeout=1)
        process.terminate.assert_called_once()
    finally:
        release_write.set()
        play_thread.join(timeout=2)
        stop_thread.join(timeout=2)


@pytest.mark.parametrize("error", [BrokenPipeError("pipe"), OSError("device")])
def test_play_propagates_unexpected_stdin_errors(error) -> None:
    process = Mock()
    process.poll.return_value = None
    process.stdin.write.side_effect = error
    player = AudioPlayer(22050)
    player._proc = process

    with pytest.raises(type(error), match=str(error)):
        player.play(b"audio")
