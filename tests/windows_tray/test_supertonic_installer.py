"""On-demand installation of the pinned Supertonic 3 model assets."""

import hashlib
import io
import json
import threading
import sys

import pytest


def _installer():
    from piper import supertonic_installer

    return supertonic_installer


class _Response(io.BytesIO):
    def __init__(self, data=b"", *, headers=None):
        super().__init__(data)
        self.headers = headers or {}

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        self.close()


def _fake_repository(installer, tmp_path, monkeypatch):
    contents = {
        relative: ("asset:" + relative).encode("utf-8")
        for relative in installer.ASSET_PATHS
    }
    calls = []
    worker_source = tmp_path / "bundled-worker"
    worker_source.mkdir()
    (worker_source / "SupertonicWorker.exe").write_bytes(b"worker-executable")
    (worker_source / "onnxruntime.dll").write_bytes(b"worker-runtime")
    monkeypatch.setenv("PIPER_SUPERTONIC_WORKER_DIR", str(worker_source))
    monkeypatch.delenv("PIPER_SUPERTONIC_WORKER_PYTHON", raising=False)

    def open_url(request, timeout):
        url = request.full_url if hasattr(request, "full_url") else request
        method = request.get_method() if hasattr(request, "get_method") else "GET"
        calls.append((url, method, timeout))
        relative = installer.asset_path_for_url(url)
        data = contents[relative]
        headers = {"Content-Length": str(len(data))}
        return _Response(b"" if method == "HEAD" else data, headers=headers)

    return contents, calls, open_url


def test_supertonic_assets_are_pinned_to_the_official_model_snapshot():
    installer = _installer()

    assert installer.ENGINE == "Supertonic 3"
    assert installer.MODEL_REPO == "Supertone/supertonic-3"
    assert installer.MODEL_REVISION == "3cadd1ee6394adea1bd021217a0e650ede09a323"
    assert installer.SOURCE_REPO == "supertone-oss-archive/supertonic-py"
    assert installer.SOURCE_REVISION == "df0f9686dac7fbbde391b759e2ee5286a3737622"
    assert {
        "onnx/duration_predictor.onnx",
        "onnx/text_encoder.onnx",
        "onnx/vector_estimator.onnx",
        "onnx/vocoder.onnx",
        "onnx/tts.json",
        "onnx/unicode_indexer.json",
        "config.json",
        "LICENSE",
        "SOURCE-LICENSE",
    } <= set(installer.ASSET_PATHS)
    assert {f"voice_styles/{voice}.json" for voice in (
        "M1", "M2", "M3", "M4", "M5", "F1", "F2", "F3", "F4", "F5"
    )} <= set(installer.ASSET_PATHS)


def test_install_downloads_pinned_files_and_writes_runtime_manifest(tmp_path, monkeypatch):
    installer = _installer()
    contents, calls, open_url = _fake_repository(installer, tmp_path, monkeypatch)
    monkeypatch.setattr(installer, "urlopen", open_url)
    install_root = tmp_path / "Piper" / "Supertonic3"
    updates = []

    installed = installer.install_supertonic3(
        lambda completed, total, component: updates.append(
            (completed, total, component)
        ),
        threading.Event(),
        install_root=install_root,
    )

    assert installed == install_root.resolve()
    manifest_path = install_root / "model_assets.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert manifest == {
        "manifest_version": 1,
        "engine": "Supertonic 3",
        "model_repo": "Supertone/supertonic-3",
        "model_revision": "3cadd1ee6394adea1bd021217a0e650ede09a323",
        "source_repo": "supertone-oss-archive/supertonic-py",
        "source_revision": "df0f9686dac7fbbde391b759e2ee5286a3737622",
        "files": {
            **{
                relative: hashlib.sha256(data).hexdigest()
                for relative, data in contents.items()
            },
            "worker/SupertonicWorker.exe": hashlib.sha256(b"worker-executable").hexdigest(),
            "worker/onnxruntime.dll": hashlib.sha256(b"worker-runtime").hexdigest(),
        },
    }
    assert all((install_root / relative).read_bytes() == data
               for relative, data in contents.items())
    assert (install_root / "worker" / "SupertonicWorker.exe").read_bytes() == b"worker-executable"
    assert all(url.startswith(
        "https://huggingface.co/Supertone/supertonic-3/resolve/"
        "3cadd1ee6394adea1bd021217a0e650ede09a323/"
    ) or url.startswith(
        "https://raw.githubusercontent.com/supertone-oss-archive/supertonic-py/"
        "df0f9686dac7fbbde391b759e2ee5286a3737622/"
    ) for url, _method, _timeout in calls)
    assert {method for _url, method, _timeout in calls} == {"GET", "HEAD"}
    assert updates[-1][0] == updates[-1][1]
    assert installer.supertonic3_installed(install_root=install_root)


def test_installed_supertonic_model_is_detected_offline_and_corruption_is_rejected(
    tmp_path, monkeypatch
):
    installer = _installer()
    contents, _calls, open_url = _fake_repository(installer, tmp_path, monkeypatch)
    monkeypatch.setattr(installer, "urlopen", open_url)
    install_root = tmp_path / "Piper" / "Supertonic3"
    installer.install_supertonic3(lambda *_args: None, threading.Event(),
                                   install_root=install_root)

    monkeypatch.setattr(
        installer, "urlopen", lambda *_args, **_kwargs: pytest.fail("network access")
    )
    assert installer.supertonic3_installed(install_root=install_root)

    corrupted = install_root / "onnx" / "text_encoder.onnx"
    corrupted.write_bytes(contents["onnx/text_encoder.onnx"] + b"corrupt")
    assert not installer.supertonic3_installed(install_root=install_root)


def test_cancelled_download_does_not_replace_existing_install(tmp_path, monkeypatch):
    installer = _installer()
    contents, _calls, open_url = _fake_repository(installer, tmp_path, monkeypatch)
    monkeypatch.setattr(installer, "urlopen", open_url)
    install_root = tmp_path / "Piper" / "Supertonic3"
    installer.install_supertonic3(lambda *_args: None, threading.Event(),
                                   install_root=install_root)
    previous_manifest = (install_root / "model_assets.json").read_bytes()
    (install_root / "worker" / "onnxruntime.dll").write_bytes(b"local previous content")

    cancel_event = threading.Event()

    def cancel_after_first_chunk(completed, _total, _component):
        if completed:
            cancel_event.set()

    with pytest.raises(installer.DownloadCancelled):
        installer.install_supertonic3(
            cancel_after_first_chunk, cancel_event, install_root=install_root
        )

    assert (install_root / "model_assets.json").read_bytes() == previous_manifest
    assert (install_root / "worker" / "onnxruntime.dll").read_bytes() == b"local previous content"
    assert not list(install_root.parent.glob("Supertonic3.staging-*"))


def test_default_install_location_uses_appdata_piper_supertonic3(monkeypatch, tmp_path):
    installer = _installer()
    monkeypatch.setenv("APPDATA", str(tmp_path / "AppData"))

    assert installer.installation_root() == tmp_path / "AppData" / "Piper" / "Supertonic3"


def test_dev_worker_interpreter_allows_model_install_without_packaged_worker(
    tmp_path, monkeypatch
):
    installer = _installer()
    monkeypatch.delenv("PIPER_SUPERTONIC_WORKER_DIR", raising=False)
    monkeypatch.setenv("PIPER_SUPERTONIC_WORKER_PYTHON", sys.executable)
    contents, _calls, open_url = _fake_repository(installer, tmp_path, monkeypatch)
    monkeypatch.delenv("PIPER_SUPERTONIC_WORKER_DIR", raising=False)
    monkeypatch.setenv("PIPER_SUPERTONIC_WORKER_PYTHON", sys.executable)
    monkeypatch.setattr(installer, "urlopen", open_url)
    install_root = tmp_path / "Piper" / "Supertonic3"

    installer.install_supertonic3(lambda *_args: None, threading.Event(),
                                   install_root=install_root)

    assert installer.supertonic3_installed(install_root=install_root)
    assert not (install_root / "worker").exists()
    assert (install_root / "config.json").read_bytes() == contents["config.json"]


def test_frozen_app_worker_is_copied_into_user_install(tmp_path, monkeypatch):
    installer = _installer()
    _contents, _calls, open_url = _fake_repository(installer, tmp_path, monkeypatch)
    monkeypatch.delenv("PIPER_SUPERTONIC_WORKER_DIR", raising=False)
    frozen_root = tmp_path / "frozen"
    worker_source = frozen_root / "supertonic_worker"
    worker_source.mkdir(parents=True)
    (worker_source / "SupertonicWorker.exe").write_bytes(b"frozen-worker")
    (worker_source / "runtime.dll").write_bytes(b"frozen-runtime")
    monkeypatch.setattr(installer.sys, "_MEIPASS", str(frozen_root), raising=False)
    monkeypatch.setattr(installer, "urlopen", open_url)
    install_root = tmp_path / "Piper" / "Supertonic3"

    installer.install_supertonic3(lambda *_args: None, threading.Event(),
                                   install_root=install_root)

    assert (install_root / "worker" / "SupertonicWorker.exe").read_bytes() == b"frozen-worker"
    assert (install_root / "worker" / "runtime.dll").read_bytes() == b"frozen-runtime"


def test_model_install_fails_before_download_if_no_worker_runtime_is_available(
    tmp_path, monkeypatch
):
    installer = _installer()
    monkeypatch.delenv("PIPER_SUPERTONIC_WORKER_DIR", raising=False)
    monkeypatch.delenv("PIPER_SUPERTONIC_WORKER_PYTHON", raising=False)
    monkeypatch.setattr(
        installer, "urlopen", lambda *_args, **_kwargs: pytest.fail("network access")
    )

    with pytest.raises(installer.SupertonicInstallError, match="worker runtime"):
        installer.install_supertonic3(
            lambda *_args: None,
            threading.Event(),
            install_root=tmp_path / "Piper" / "Supertonic3",
        )
