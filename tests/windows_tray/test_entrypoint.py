import importlib
import sys


def test_entrypoint_rejects_non_windows_before_loading_desktop_modules(
    monkeypatch, capsys
) -> None:
    module = importlib.import_module("piper.windows_tray.__main__")
    monkeypatch.setattr(sys, "platform", "linux")

    assert module.main([]) == 2
    assert "Windows" in capsys.readouterr().err
    assert "piper.windows_tray.app" not in sys.modules
