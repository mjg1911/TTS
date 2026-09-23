"""Windows process helpers for binding the Kokoro worker to the tray."""

from __future__ import annotations

import ctypes
from ctypes import wintypes
import os
import subprocess
from typing import Callable, Optional


CREATE_NO_WINDOW = 0x08000000
JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE = 0x00002000
JobObjectExtendedLimitInformation = 9


class JOBOBJECT_BASIC_LIMIT_INFORMATION(ctypes.Structure):
    _fields_ = [
        ("PerProcessUserTimeLimit", ctypes.c_longlong),
        ("PerJobUserTimeLimit", ctypes.c_longlong),
        ("LimitFlags", wintypes.DWORD),
        ("MinimumWorkingSetSize", ctypes.c_size_t),
        ("MaximumWorkingSetSize", ctypes.c_size_t),
        ("ActiveProcessLimit", wintypes.DWORD),
        ("Affinity", ctypes.c_size_t),
        ("PriorityClass", wintypes.DWORD),
        ("SchedulingClass", wintypes.DWORD),
    ]


class IO_COUNTERS(ctypes.Structure):
    _fields_ = [
        ("ReadOperationCount", ctypes.c_ulonglong),
        ("WriteOperationCount", ctypes.c_ulonglong),
        ("OtherOperationCount", ctypes.c_ulonglong),
        ("ReadTransferCount", ctypes.c_ulonglong),
        ("WriteTransferCount", ctypes.c_ulonglong),
        ("OtherTransferCount", ctypes.c_ulonglong),
    ]


class JOBOBJECT_EXTENDED_LIMIT_INFORMATION(ctypes.Structure):
    _fields_ = [
        ("BasicLimitInformation", JOBOBJECT_BASIC_LIMIT_INFORMATION),
        ("IoInfo", IO_COUNTERS),
        ("ProcessMemoryLimit", ctypes.c_size_t),
        ("JobMemoryLimit", ctypes.c_size_t),
        ("PeakProcessMemoryUsed", ctypes.c_size_t),
        ("PeakJobMemoryUsed", ctypes.c_size_t),
    ]


def _win32_job_functions():
    if os.name != "nt":
        raise OSError("Kokoro worker process binding is Windows-only")
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)

    def create_job():
        handle = kernel32.CreateJobObjectW(None, None)
        if not handle:
            raise ctypes.WinError(ctypes.get_last_error())
        return handle

    def configure_job(handle):
        info = JOBOBJECT_EXTENDED_LIMIT_INFORMATION()
        info.BasicLimitInformation.LimitFlags = JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
        if not kernel32.SetInformationJobObject(
            handle,
            JobObjectExtendedLimitInformation,
            ctypes.byref(info),
            ctypes.sizeof(info),
        ):
            raise ctypes.WinError(ctypes.get_last_error())

    def assign_process(handle, process_handle):
        if not kernel32.AssignProcessToJobObject(handle, process_handle):
            raise ctypes.WinError(ctypes.get_last_error())

    def close_handle(handle):
        kernel32.CloseHandle(handle)

    return create_job, configure_job, assign_process, close_handle


class WindowsKillOnCloseJob:
    def __init__(
        self,
        create_job: Optional[Callable[[], int]] = None,
        configure_job: Optional[Callable[[int], None]] = None,
        assign_process: Optional[Callable[[int, int], None]] = None,
        close_handle: Optional[Callable[[int], None]] = None,
    ) -> None:
        if create_job is None:
            create_job, configure_job, assign_process, close_handle = _win32_job_functions()
        self._configure_job = configure_job
        self._assign_process = assign_process
        self._close_handle = close_handle
        self._handle = create_job()
        try:
            self._configure_job(self._handle)
        except BaseException:
            handle = self._handle
            self._handle = None
            self._close_handle(handle)
            raise

    def assign(self, process: object) -> None:
        self._assign_process(self._handle, int(process._handle))

    def close(self) -> None:
        if self._handle is not None:
            handle = self._handle
            self._handle = None
            self._close_handle(handle)


def launch_kokoro_worker(
    config,
    *,
    popen=subprocess.Popen,
    job_factory=WindowsKillOnCloseJob,
):
    process = popen(
        [str(config.executable)],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        creationflags=CREATE_NO_WINDOW,
    )
    job = None
    try:
        job = job_factory()
        job.assign(process)
    except BaseException:
        try:
            process.kill()
        finally:
            if job is not None:
                job.close()
        raise
    process._piper_kokoro_job = job
    return process
