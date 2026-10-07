"""End-to-end tests for verified local Chatterbox model downloads."""
from concurrent.futures import ThreadPoolExecutor
import hashlib
import io
import json
from pathlib import Path
import threading
import time
import zipfile

import pytest

from piper import nano_assets, turbo_assets
from piper import chatterbox_assets
from piper.windows_tray import model_download


def _archive(files):
    stream = io.BytesIO()
    with zipfile.ZipFile(stream, "w", zipfile.ZIP_DEFLATED) as archive:
        for name, content in files.items():
            archive.writestr(name, content)
    return stream.getvalue()


def _fixture_catalog(tmp_path, monkeypatch, *, unsafe_model_path=None):
    nano_contents = {
        name: ("nano:" + name).encode() for name in nano_assets.REQUIRED_MODEL_FILES
    }
    turbo_contents = {
        name: ("turbo:" + name).encode() for name in turbo_assets.REQUIRED_MODEL_FILES
    }
    monkeypatch.setattr(
        nano_assets,
        "MODEL_FILE_SHA256",
        {name: hashlib.sha256(data).hexdigest() for name, data in nano_contents.items()},
    )
    monkeypatch.setattr(
        turbo_assets,
        "MODEL_FILE_SHA256",
        {name: hashlib.sha256(data).hexdigest() for name, data in turbo_contents.items()},
    )

    payloads = {
        "worker": _archive({"worker/ChatterboxWorker.exe": b"shared-worker"}),
        "nano": _archive(
            {
                (unsafe_model_path or f"models/nano/{name}"): data
                for name, data in nano_contents.items()
            }
        ),
        "turbo": _archive(
            {f"models/turbo/{name}": data for name, data in turbo_contents.items()}
        ),
    }
    catalog = {
        "version": 1,
        "release": "v1.10.0",
        "components": {
            component: {
                "parts": [
                    {
                        "url": f"https://assets.invalid/{component}.zip",
                        "size": len(data),
                        "sha256": hashlib.sha256(data).hexdigest(),
                    }
                ]
            }
            for component, data in payloads.items()
        },
    }
    catalog_path = tmp_path / "catalog.json"
    catalog_path.write_text(json.dumps(catalog), encoding="utf-8")
    streams = {f"https://assets.invalid/{key}.zip": data for key, data in payloads.items()}
    calls = []

    def open_url(url, timeout):
        if hasattr(url, "full_url"):
            url = url.full_url
        calls.append(url)
        return io.BytesIO(streams[url])

    monkeypatch.setattr(model_download, "urlopen", open_url)
    return catalog_path, streams, calls


def _download(engine, catalog_path, install_root, *, cancel_event=None, progress=None):
    return model_download.download_engine(
        engine,
        progress or (lambda *_: None),
        cancel_event or threading.Event(),
        catalog_path=catalog_path,
        install_root=install_root,
    )


def test_fresh_engine_is_missing_without_making_a_network_request(tmp_path, monkeypatch):
    catalog_path, _streams, calls = _fixture_catalog(tmp_path, monkeypatch)

    assert not model_download.engine_installed(
        "Chatterbox Nano", catalog_path=catalog_path, install_root=tmp_path / "Piper"
    )
    assert calls == []


def test_downloaded_engine_is_verified_and_usable_offline(tmp_path, monkeypatch):
    catalog_path, _streams, calls = _fixture_catalog(tmp_path, monkeypatch)
    install_root = tmp_path / "Piper"
    updates = []

    generation = _download(
        "Chatterbox Nano", catalog_path, install_root, progress=lambda *args: updates.append(args)
    )

    installation = nano_assets.inspect_nano_installation(generation)
    assert installation.worker_executable.read_bytes() == b"shared-worker"
    assert installation.model_dir == generation / "models" / "nano"
    assert model_download.engine_installed(
        "nano", catalog_path=catalog_path, install_root=install_root
    )
    assert len(calls) == 2
    assert updates and updates[-1][0] == updates[-1][1]

    def offline(*_args, **_kwargs):
        raise AssertionError("readiness inspection must not access the network")

    monkeypatch.setattr(model_download, "urlopen", offline)
    model_download.invalidate_installation_cache("nano", install_root)
    assert model_download.engine_installed(
        "Chatterbox Nano", catalog_path=catalog_path, install_root=install_root
    )
    monkeypatch.setattr(
        chatterbox_assets,
        "inspect_chatterbox_installation",
        lambda *_args: pytest.fail("cached readiness must not rehash the payload"),
    )
    assert model_download.engine_installed(
        "Chatterbox Nano", catalog_path=catalog_path, install_root=install_root
    )


def test_multipart_zip_is_reassembled_after_each_part_is_verified(tmp_path, monkeypatch):
    catalog_path, streams, calls = _fixture_catalog(tmp_path, monkeypatch)
    catalog = json.loads(catalog_path.read_text(encoding="utf-8"))
    original = streams.pop("https://assets.invalid/worker.zip")
    split = len(original) // 2
    parts = (original[:split], original[split:])
    catalog["components"]["worker"]["parts"] = []
    for index, data in enumerate(parts, start=1):
        url = f"https://assets.invalid/worker-{index}.part"
        streams[url] = data
        catalog["components"]["worker"]["parts"].append(
            {"url": url, "size": len(data), "sha256": hashlib.sha256(data).hexdigest()}
        )
    catalog_path.write_text(json.dumps(catalog), encoding="utf-8")

    generation = _download("nano", catalog_path, tmp_path / "Piper")

    assert (generation / "worker" / "ChatterboxWorker.exe").read_bytes() == b"shared-worker"
    assert calls.count("https://assets.invalid/worker-1.part") == 1
    assert calls.count("https://assets.invalid/worker-2.part") == 1


def test_second_engine_retains_first_and_reuses_the_shared_worker(tmp_path, monkeypatch):
    catalog_path, _streams, calls = _fixture_catalog(tmp_path, monkeypatch)
    install_root = tmp_path / "Piper"

    nano_root = _download("nano", catalog_path, install_root)
    turbo_root = _download("Chatterbox Turbo (350M)", catalog_path, install_root)

    nano_assets.inspect_nano_installation(turbo_root)
    turbo_assets.inspect_turbo_installation(turbo_root)
    assert nano_root != turbo_root
    assert (turbo_root / "worker" / "ChatterboxWorker.exe").read_bytes() == b"shared-worker"
    assert calls.count("https://assets.invalid/worker.zip") == 1
    manifest = json.loads((turbo_root / "manifest.json").read_text(encoding="utf-8"))
    assert set(manifest["models"]) == {"nano", "turbo"}
    nano_assets.inspect_nano_installation(nano_root)
    assert (nano_root / "worker" / "ChatterboxWorker.exe").read_bytes() == b"shared-worker"


@pytest.mark.parametrize("bad_field", ["sha256", "size"])
def test_wrong_part_hash_or_size_rolls_back_without_activation(
    tmp_path, monkeypatch, bad_field
):
    catalog_path, _streams, _calls = _fixture_catalog(tmp_path, monkeypatch)
    catalog = json.loads(catalog_path.read_text(encoding="utf-8"))
    part = catalog["components"]["worker"]["parts"][0]
    part[bad_field] = "0" * 64 if bad_field == "sha256" else part["size"] + 1
    catalog_path.write_text(json.dumps(catalog), encoding="utf-8")
    install_root = tmp_path / "Piper"

    with pytest.raises(model_download.ModelDownloadError, match="worker"):
        _download("nano", catalog_path, install_root)

    assert model_download.active_generation_root(install_root) is None
    assert not model_download.engine_installed(
        "nano", catalog_path=catalog_path, install_root=install_root
    )


def test_cancelled_download_leaves_no_active_generation(tmp_path, monkeypatch):
    catalog_path, _streams, _calls = _fixture_catalog(tmp_path, monkeypatch)
    cancel_event = threading.Event()
    install_root = tmp_path / "Piper"

    class CancellingStream(io.BytesIO):
        def read(self, size=-1):
            data = super().read(min(size, 32))
            if data:
                cancel_event.set()
            return data

    monkeypatch.setattr(
        model_download,
        "urlopen",
        lambda _url, timeout: CancellingStream(
            _streams["https://assets.invalid/worker.zip"]
        ),
    )

    with pytest.raises(model_download.DownloadCancelled):
        _download("nano", catalog_path, install_root, cancel_event=cancel_event)

    assert model_download.active_generation_root(install_root) is None


def test_unsafe_archive_paths_are_rejected_and_never_written_outside_staging(
    tmp_path, monkeypatch
):
    outside = tmp_path / "escape.bin"
    catalog_path, _streams, _calls = _fixture_catalog(
        tmp_path, monkeypatch, unsafe_model_path="models/nano/../../escape.bin"
    )
    install_root = tmp_path / "Piper"

    with pytest.raises(model_download.ModelDownloadError, match="path"):
        _download("nano", catalog_path, install_root)

    assert not outside.exists()
    assert model_download.active_generation_root(install_root) is None


def test_installers_are_serialized_and_preserve_both_models(tmp_path, monkeypatch):
    catalog_path, streams, _calls = _fixture_catalog(tmp_path, monkeypatch)
    install_root = tmp_path / "Piper"
    first_read = threading.Event()
    release_first = threading.Event()
    first_url = "https://assets.invalid/worker.zip"
    original = model_download.urlopen
    first_stream = True

    class BlockingStream(io.BytesIO):
        def read(self, size=-1):
            first_read.set()
            assert release_first.wait(3)
            return super().read(size)

    def open_url(url, timeout):
        nonlocal first_stream
        if hasattr(url, "full_url"):
            url = url.full_url
        if url == first_url and first_stream:
            first_stream = False
            return BlockingStream(streams[url])
        return original(url, timeout)

    monkeypatch.setattr(model_download, "urlopen", open_url)
    with ThreadPoolExecutor(max_workers=2) as pool:
        nano_future = pool.submit(_download, "nano", catalog_path, install_root)
        assert first_read.wait(2)
        turbo_future = pool.submit(_download, "turbo", catalog_path, install_root)
        time.sleep(0.05)
        assert not turbo_future.done()
        release_first.set()
        nano_future.result(timeout=5)
        turbo_root = turbo_future.result(timeout=5)

    nano_assets.inspect_nano_installation(turbo_root)
    turbo_assets.inspect_turbo_installation(turbo_root)


def test_failed_second_engine_download_keeps_previous_generation_active(
    tmp_path, monkeypatch
):
    catalog_path, _streams, _calls = _fixture_catalog(tmp_path, monkeypatch)
    install_root = tmp_path / "Piper"
    first_root = _download("nano", catalog_path, install_root)
    catalog = json.loads(catalog_path.read_text(encoding="utf-8"))
    catalog["components"]["turbo"]["parts"][0]["sha256"] = "0" * 64
    catalog_path.write_text(json.dumps(catalog), encoding="utf-8")

    with pytest.raises(model_download.ModelDownloadError, match="turbo"):
        _download("turbo", catalog_path, install_root)

    assert model_download.active_generation_root(install_root) == first_root
    assert model_download.engine_installed(
        "nano", catalog_path=catalog_path, install_root=install_root
    )
    assert not model_download.engine_installed(
        "turbo", catalog_path=catalog_path, install_root=install_root
    )


def test_pointer_swap_failure_rolls_back_the_new_generation(tmp_path, monkeypatch):
    catalog_path, _streams, _calls = _fixture_catalog(tmp_path, monkeypatch)
    install_root = tmp_path / "Piper"
    first_root = _download("nano", catalog_path, install_root)
    real_replace = model_download.os.replace

    def fail_pointer_swap(source, destination):
        if Path(destination) == install_root / "current.json":
            raise OSError("simulated pointer write failure")
        return real_replace(source, destination)

    monkeypatch.setattr(model_download.os, "replace", fail_pointer_swap)
    with pytest.raises(model_download.ModelDownloadError, match="pointer write failure"):
        _download("turbo", catalog_path, install_root)

    assert model_download.active_generation_root(install_root) == first_root
    assert len(list((install_root / "generations").iterdir())) == 1
    nano_assets.inspect_nano_installation(first_root)


def test_unprepared_catalog_reports_assets_not_configured(tmp_path, monkeypatch):
    catalog_path = tmp_path / "catalog.json"
    catalog_path.write_text(
        json.dumps(
            {
                "version": 1,
                "release": "v1.10.0",
                "components": {name: {"parts": []} for name in ("worker", "nano", "turbo")},
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(model_download, "urlopen", lambda *_args, **_kwargs: pytest.fail("network"))

    with pytest.raises(model_download.ModelDownloadError, match="not configured"):
        _download("nano", catalog_path, tmp_path / "Piper")


def test_app_discovery_uses_the_active_persistent_generation(monkeypatch, tmp_path):
    from piper.windows_tray import app

    appdata = tmp_path / "user"
    store = appdata / "Piper" / "Chatterbox"
    generation = store / "generations" / ("a" * 32)
    generation.mkdir(parents=True)
    monkeypatch.setenv("APPDATA", str(appdata))
    monkeypatch.delattr(app.sys, "_MEIPASS", raising=False)
    (store / "current.json").write_text(
        json.dumps({"version": 1, "generation": f"generations/{generation.name}"}),
        encoding="utf-8",
    )

    assert list(app._shared_chatterbox_roots()) == [generation.resolve()]


def test_app_discovery_uses_local_appdata_when_appdata_is_unset(monkeypatch, tmp_path):
    from piper.windows_tray import app

    local_appdata = tmp_path / "local-user"
    store = local_appdata / "Piper" / "Chatterbox"
    generation = store / "generations" / ("b" * 32)
    generation.mkdir(parents=True)
    monkeypatch.delenv("APPDATA", raising=False)
    monkeypatch.setenv("LOCALAPPDATA", str(local_appdata))
    monkeypatch.delattr(app.sys, "_MEIPASS", raising=False)
    (store / "current.json").write_text(
        json.dumps({"version": 1, "generation": f"generations/{generation.name}"}),
        encoding="utf-8",
    )

    assert list(app._shared_chatterbox_roots()) == [generation.resolve()]
    assert app._nano_root() == local_appdata / "Piper" / "ChatterboxNano"
    assert app._turbo_root() == local_appdata / "Piper" / "ChatterboxTurbo"
