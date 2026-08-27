from unittest.mock import Mock

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
