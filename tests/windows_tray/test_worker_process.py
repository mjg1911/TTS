from types import SimpleNamespace

import pytest

from piper.windows_tray.worker_process import (
    CREATE_NO_WINDOW,
    WindowsKillOnCloseJob,
)


def test_create_no_window_retains_windows_subprocess_flag():
    assert CREATE_NO_WINDOW == 0x08000000


def test_job_configures_kill_on_close_and_assigns_process_handle():
    calls = []
    job = WindowsKillOnCloseJob(
        create_job=lambda: 77,
        configure_job=lambda handle: calls.append(("configure", handle)),
        assign_process=lambda handle, process_handle: calls.append(
            ("assign", handle, process_handle)
        ),
        close_handle=lambda handle: calls.append(("close", handle)),
    )
    process = SimpleNamespace(_handle=123)

    job.assign(process)
    job.close()

    assert calls == [("configure", 77), ("assign", 77, 123), ("close", 77)]


def test_job_closes_handle_when_configuration_fails():
    closed = []

    def fail_configuration(_handle):
        raise OSError("configuration failed")

    with pytest.raises(OSError, match="configuration failed"):
        WindowsKillOnCloseJob(
            create_job=lambda: 77,
            configure_job=fail_configuration,
            assign_process=lambda _handle, _process_handle: None,
            close_handle=closed.append,
        )

    assert closed == [77]


def test_job_close_is_idempotent():
    closed = []
    job = WindowsKillOnCloseJob(
        create_job=lambda: 77,
        configure_job=lambda handle: None,
        assign_process=lambda handle, process_handle: None,
        close_handle=lambda handle: closed.append(handle),
    )

    job.close()
    job.close()

    assert closed == [77]
