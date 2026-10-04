import importlib
import pytest


def test_supported_language_list():
    options = importlib.import_module('piper.multilingual_options')
    assert len(options.SUPPORTED_LANGUAGES) == 23
    assert options.SUPPORTED_LANGUAGES['nl'] == 'Dutch'
    assert options.validate_language('en') == 'en'


@pytest.mark.parametrize('function,value', [('validate_language','EN'), ('validate_exaggeration',0), ('validate_cfg_weight',float('inf')), ('validate_cfg_weight',True)])
def test_invalid_options(function, value):
    options = importlib.import_module('piper.multilingual_options')
    with pytest.raises(ValueError):
        getattr(options, function)(value)
