import importlib


def test_turbo_engine_label_is_shared_by_worker_and_tray():
    options = importlib.import_module('piper.turbo_options')
    assert options.ENGINE == 'Chatterbox Turbo (350M)'
