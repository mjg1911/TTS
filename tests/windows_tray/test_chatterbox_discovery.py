"""Both engine clients discover the same installed worker payload."""
from pathlib import Path
import sys

import pytest

from piper.windows_tray import app


@pytest.mark.parametrize('engine', ['nano', 'turbo'])
def test_bundled_shared_payload_is_preferred(monkeypatch, tmp_path, engine):
    import piper.nano_assets as nano_assets
    import piper.turbo_assets as turbo_assets

    monkeypatch.setenv('APPDATA', str(tmp_path / 'user'))
    monkeypatch.setattr(sys, '_MEIPASS', str(tmp_path / 'bundle'), raising=False)
    shared = tmp_path / 'bundle' / 'chatterbox_payload'
    shared.mkdir(parents=True)
    (tmp_path / 'bundle' / f'{engine}_payload').mkdir()
    calls = []
    module = nano_assets if engine == 'nano' else turbo_assets
    monkeypatch.setattr(module, f'inspect_{engine}_installation',
                        lambda root: calls.append(Path(root)) or 'installation')
    assert getattr(app, f'_prepare_{engine}_installation')() == 'installation'
    assert calls == [shared]


@pytest.mark.parametrize('engine', ['nano', 'turbo'])
def test_user_shared_payload_is_preferred_over_legacy(monkeypatch, tmp_path, engine):
    import piper.nano_assets as nano_assets
    import piper.turbo_assets as turbo_assets

    monkeypatch.setenv('APPDATA', str(tmp_path))
    monkeypatch.delattr(sys, '_MEIPASS', raising=False)
    shared = tmp_path / 'Piper' / 'Chatterbox'
    shared.mkdir(parents=True)
    calls = []
    module = nano_assets if engine == 'nano' else turbo_assets
    monkeypatch.setattr(module, f'inspect_{engine}_installation',
                        lambda root: calls.append(Path(root)) or 'installation')
    assert getattr(app, f'_prepare_{engine}_installation')() == 'installation'
    assert calls == [shared]


@pytest.mark.parametrize('engine,dirname', [('nano', 'ChatterboxNano'), ('turbo', 'ChatterboxTurbo')])
def test_legacy_payload_remains_discoverable(monkeypatch, tmp_path, engine, dirname):
    import piper.nano_assets as nano_assets
    import piper.turbo_assets as turbo_assets

    monkeypatch.setenv('APPDATA', str(tmp_path))
    monkeypatch.delattr(sys, '_MEIPASS', raising=False)
    calls = []
    module = nano_assets if engine == 'nano' else turbo_assets
    monkeypatch.setattr(module, f'inspect_{engine}_installation',
                        lambda root: calls.append(Path(root)) or 'installation')
    assert getattr(app, f'_prepare_{engine}_installation')() == 'installation'
    assert calls == [tmp_path / 'Piper' / dirname]


def test_shared_integrity_failure_reaches_backend_fallback(monkeypatch, tmp_path):
    import piper.nano_assets as nano_assets
    from piper.windows_tray.backend_manager import BackendPreparationError

    monkeypatch.setenv('APPDATA', str(tmp_path))
    monkeypatch.delattr(sys, '_MEIPASS', raising=False)
    shared = tmp_path / 'Piper' / 'Chatterbox'
    shared.mkdir(parents=True)
    calls = []

    def corrupt(root):
        calls.append(Path(root))
        raise ValueError('runtime hash mismatch')

    monkeypatch.setattr(nano_assets, 'inspect_nano_installation', corrupt)
    with pytest.raises(BackendPreparationError):
        app._prepare_nano_backend()
    assert calls == [shared]


@pytest.mark.parametrize('engine', ['nano', 'turbo'])
@pytest.mark.parametrize('user_shared_available', [True, False])
def test_missing_bundled_engine_can_use_an_existing_installation(
    monkeypatch, tmp_path, engine, user_shared_available
):
    import piper.nano_assets as nano_assets
    import piper.turbo_assets as turbo_assets
    from piper.chatterbox_assets import ChatterboxEngineUnavailable

    monkeypatch.setenv('APPDATA', str(tmp_path / 'user'))
    monkeypatch.setattr(sys, '_MEIPASS', str(tmp_path / 'bundle'), raising=False)
    bundled = tmp_path / 'bundle' / 'chatterbox_payload'
    bundled.mkdir(parents=True)
    installed = tmp_path / 'user' / 'Piper' / 'Chatterbox'
    if user_shared_available:
        installed.mkdir(parents=True)
    calls = []

    def inspect(root):
        calls.append(Path(root))
        if root == bundled:
            raise ChatterboxEngineUnavailable('selected engine is absent')
        return 'installation'

    module = nano_assets if engine == 'nano' else turbo_assets
    monkeypatch.setattr(module, f'inspect_{engine}_installation', inspect)
    assert getattr(app, f'_prepare_{engine}_installation')() == 'installation'
    legacy = tmp_path / 'user' / 'Piper' / ('ChatterboxNano' if engine == 'nano' else 'ChatterboxTurbo')
    assert calls == [bundled, installed if user_shared_available else legacy]
