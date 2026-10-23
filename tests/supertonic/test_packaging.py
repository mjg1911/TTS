import ast
from pathlib import Path
import sys
from types import ModuleType, SimpleNamespace


ROOT = Path(__file__).resolve().parents[2]


def test_distribution_includes_supertonic_worker_package():
    tree = ast.parse((ROOT / 'setup.py').read_text())
    packages = next(
        keyword.value for node in ast.walk(tree) if isinstance(node, ast.Call)
        for keyword in node.keywords if keyword.arg == 'packages'
    )
    assert 'piper.supertonic_worker' in ast.literal_eval(packages)


def test_frozen_worker_uses_absolute_import_entry_point():
    entry = (ROOT / 'script/supertonic_worker_entry.py').read_text()
    tree = ast.parse(entry)
    assert any(isinstance(node, ast.ImportFrom) and node.level == 0
               and node.module == 'piper.supertonic_worker.main' for node in ast.walk(tree))
    spec = (ROOT / 'script/supertonic_worker.spec').read_text()
    assert 'supertonic_worker_entry.py' in spec


def test_frozen_worker_includes_cuda_namespace_dlls(tmp_path, monkeypatch):
    """NVIDIA wheel folders lack __init__.py and cannot be listed as modules."""
    libraries = [
        tmp_path / 'nvidia/cu13/bin/x86_64/cudart64_13.dll',
        tmp_path / 'nvidia/cudnn/bin/cudnn64_9.dll',
    ]
    for library in libraries:
        library.parent.mkdir(parents=True, exist_ok=True)
        library.write_bytes(b'fixture')
    hooks = ModuleType('PyInstaller.utils.hooks')
    hooks.collect_data_files = lambda *a: []
    hooks.collect_dynamic_libs = lambda *a: []
    hooks.collect_submodules = lambda *a: []
    hooks.copy_metadata = lambda *a: []
    monkeypatch.setitem(sys.modules, 'PyInstaller.utils.hooks', hooks)
    monkeypatch.setattr('sysconfig.get_paths', lambda: {'purelib': str(tmp_path)})
    analysis_inputs = []

    def analysis(*args, **kwargs):
        analysis_inputs.append(kwargs)
        return SimpleNamespace(pure=[], scripts=[], binaries=[], datas=[])

    context = dict(SPECPATH=str(ROOT / 'script'), Analysis=analysis,
                   PYZ=lambda *a: None, EXE=lambda *a, **k: None,
                   COLLECT=lambda *a, **k: None)
    exec(compile((ROOT / 'script/supertonic_worker.spec').read_text(), 'spec', 'exec'), context)
    binaries = analysis_inputs[0]['binaries']
    assert (str(libraries[0]), str(Path('nvidia/cu13/bin/x86_64'))) in binaries
    assert (str(libraries[1]), str(Path('nvidia/cudnn/bin'))) in binaries
