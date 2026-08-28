import importlib


def test_core_python_api_imports_without_loading_tray_ui_dependencies(
    monkeypatch,
) -> None:
    real_import = __import__

    def guarded_import(name, *args, **kwargs):
        if name in {"pystray", "PIL", "PIL.Image"}:
            raise AssertionError(f"tray dependency imported by core API: {name}")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr("builtins.__import__", guarded_import)
    module = importlib.import_module("piper")
    importlib.reload(module)

    assert hasattr(module, "PiperVoice")
    assert hasattr(module, "SynthesisConfig")
