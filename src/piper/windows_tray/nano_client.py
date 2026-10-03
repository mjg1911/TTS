"""Tray-side Nano client sharing the bounded PCM framing and Windows jobs."""
from dataclasses import dataclass
from queue import Empty, Full, Queue
from threading import Event, Lock, Thread
import os
import subprocess
import time
from .kokoro_protocol import read_frame, write_frame, decode_audio, validate_synthesize, validate_response_frame
from .kokoro_process import WindowsKillOnCloseJob, CREATE_NO_WINDOW

class NanoUnavailable(RuntimeError):
    pass

@dataclass(frozen=True)
class NanoSynthesisResult:
    sample_rate: int
    chunks: object


def launch_nano_worker(installation):
    python = os.environ.get('PIPER_NANO_WORKER_PYTHON')
    command = ([python, '-m', 'piper.nano_worker.main'] if python else [str(installation.worker_executable)])
    environment = os.environ.copy()
    environment.update(HF_HUB_OFFLINE='1', TRANSFORMERS_OFFLINE='1')
    process = subprocess.Popen(command + ['--root', str(installation.root)], stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, env=environment, creationflags=CREATE_NO_WINDOW if os.name == 'nt' else 0)
    if os.name == 'nt':
        try:
            job = WindowsKillOnCloseJob()
            job.assign(process)
            process._nano_job = job
        except BaseException:
            process.kill()
            process.wait()
            if 'job' in locals():
                job.close()
            raise
    return process


class NanoWorkerClient:
    def __init__(self, installation, process_factory=launch_nano_worker, device='cpu'):
        if device not in ('cpu', 'cuda'):
            raise ValueError('Nano device must be cpu or cuda')
        self.installation = installation
        self._factory = process_factory
        self.device = device
        self.effective_device = 'cpu'
        self.device_message = ''
        self._process = None
        self._queue = None
        self._sample_rate = None
        self._request_id = 0
        self._closed = Event()
        self._lock = Lock()
        self._active = False

    def _dispose(self):
        process, self._process = self._process, None
        self._queue = None
        self._sample_rate = None
        self.effective_device = 'cpu'
        self.device_message = ''
        self._active = False
        if process is None:
            return
        try:
            if process.poll() is None:
                process.terminate()
                try:
                    process.wait(timeout=1)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait(timeout=1)
        finally:
            job = getattr(process, '_nano_job', None)
            if job is not None:
                job.close()
            for stream in (process.stdin, process.stdout):
                if stream is not None:
                    stream.close()

    def _read(self, cancel, timeout=300):
        deadline = time.monotonic() + timeout
        while True:
            if self._closed.is_set() or (cancel is not None and cancel.is_set()):
                raise NanoUnavailable('Nano request cancelled')
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise NanoUnavailable('Nano worker timed out')
            try:
                item = self._queue.get(timeout=min(0.05, remaining))
            except Empty:
                continue
            if isinstance(item, BaseException):
                raise NanoUnavailable('Nano worker protocol failed') from item
            return item

    def ensure_ready(self, cancel_event=None):
        with self._lock:
            if self._closed.is_set():
                raise NanoUnavailable('Nano worker is shut down')
            if cancel_event is not None and cancel_event.is_set():
                self._dispose()
                raise NanoUnavailable('Nano startup cancelled')
            if self._process is not None and self._process.poll() is None and self._sample_rate is not None:
                return
            self._dispose()
            try:
                self._process = self._factory(self.installation)
                self._queue = Queue(maxsize=8)
                queue, stream = self._queue, self._process.stdout
                def reader():
                    try:
                        while True:
                            frame = read_frame(stream)
                            while self._queue is queue and not self._closed.is_set():
                                try:
                                    queue.put(frame, timeout=0.05)
                                    break
                                except Full:
                                    pass
                            else:
                                return
                    except BaseException as error:
                        while self._queue is queue and not self._closed.is_set():
                            try:
                                queue.put(error, timeout=0.05)
                                return
                            except Full:
                                pass
                Thread(target=reader, name='nano-response-reader', daemon=True).start()
                hello = self._read(cancel_event, 10)
                if hello != {'type':'hello','engine':'Chatterbox Nano','protocol_version':1}:
                    raise NanoUnavailable('incompatible Nano worker handshake')
                initialize = {
                    'type': 'initialize',
                    'manifest_sha256': self.installation.manifest_sha256,
                }
                # Older workers accept manifest-only initialization and use CPU.
                if self.device != 'cpu':
                    initialize['device'] = self.device
                write_frame(self._process.stdin, initialize)
                ready = self._read(cancel_event)
                rate = ready.get('sample_rate')
                effective_device = ready.get('device', 'cpu')
                device_message = ready.get('device_message', '')
                if (ready.get('type') != 'ready' or type(rate) is not int
                        or not 8000 <= rate <= 192000
                        or effective_device not in ('cpu', 'cuda')
                        or effective_device == 'cuda' and self.device != 'cuda'
                        or not isinstance(device_message, str)):
                    raise NanoUnavailable('invalid Nano ready response')
                self._sample_rate = rate
                self.effective_device = effective_device
                if self.device == 'cuda' and effective_device == 'cpu' and not device_message:
                    device_message = 'CUDA unavailable; using CPU.'
                self.device_message = device_message
            except Exception as error:
                self._dispose()
                if isinstance(error, NanoUnavailable):
                    raise
                raise NanoUnavailable('Nano startup failed') from error

    def synthesize(self, text, cancel_event):
        with self._lock:
            if self._active:
                raise NanoUnavailable('Nano synthesis request already active')
        self.ensure_ready(cancel_event)
        with self._lock:
            self._request_id += 1
            request_id = self._request_id
        message = {'type':'synthesize','request_id':request_id,'text':text,'voice_id':'default'}
        try:
            validate_synthesize(message)
        except Exception as error:
            raise NanoUnavailable('invalid Nano synthesis request') from error
        # A caller may discard this iterator before playback starts. Do not
        # claim the worker or send text until the iterator is actually consumed.
        return NanoSynthesisResult(self._sample_rate, self._chunks(message, cancel_event))

    def _chunks(self, message, cancel):
        ended = False
        with self._lock:
            if self._active:
                raise NanoUnavailable('Nano synthesis request already active')
            self._active = True
        try:
            if cancel.is_set() or self._closed.is_set():
                return
            with self._lock:
                if self._process is None or self._process.poll() is not None:
                    raise NanoUnavailable('Nano worker is no longer ready')
                write_frame(self._process.stdin, message)
            while True:
                if cancel.is_set() or self._closed.is_set():
                    return
                frame = self._read(cancel)
                validate_response_frame(frame)
                if frame['request_id'] != message['request_id']:
                    raise NanoUnavailable('Nano response request mismatch')
                if frame['type'] == 'response_end':
                    ended = True
                    return
                if frame['type'] != 'audio':
                    raise NanoUnavailable('Nano synthesis failed')
                if not cancel.is_set() and not self._closed.is_set():
                    yield decode_audio(frame['audio'])
        except Exception as error:
            if cancel.is_set() or self._closed.is_set():
                return
            if isinstance(error, NanoUnavailable):
                raise
            raise NanoUnavailable('invalid Nano response') from error
        finally:
            with self._lock:
                self._active = False
                if not ended:
                    self._dispose()

    def shutdown(self):
        self._closed.set()
        with self._lock:
            self._dispose()
