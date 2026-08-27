import importlib
import sys


def test_entrypoint_rejects_non_windows_before_loading_desktop_modules(
    monkeypatch, capsys
) -> None:
    module = importlib.import_module("piper.windows_tray.__main__")
    monkeypatch.setattr(sys, "platform", "linux")
    sys.modules.pop("piper.windows_tray.app", None)

    assert module.main([]) == 2
    assert "Windows" in capsys.readouterr().err
    assert "piper.windows_tray.app" not in sys.modules


def test_app_module_import_does_not_load_tk_or_tray_dependencies(monkeypatch) -> None:
    real_import = __import__

    def guarded_import(name, *args, **kwargs):
        if name in {"tkinter", "pystray", "PIL", "PIL.Image"}:
            raise AssertionError("desktop dependency imported eagerly: %s" % name)
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr("builtins.__import__", guarded_import)
    module = importlib.import_module("piper.windows_tray.app")
    importlib.reload(module)
