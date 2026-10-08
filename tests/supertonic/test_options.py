import pytest

from piper import supertonic_options as options


def test_supertonic_3_exposes_the_documented_voices_languages_and_defaults():
    assert options.ENGINE == 'Supertonic 3'
    assert tuple(code for code, _ in options.VOICES) == (
        'M1', 'M2', 'M3', 'M4', 'M5', 'F1', 'F2', 'F3', 'F4', 'F5',
    )
    assert options.DEFAULT_VOICE == 'M1'
    assert options.DEFAULT_LANGUAGE == 'en'
    assert len(options.LANGUAGES) == 32
    assert ('en', 'English') in options.LANGUAGES
    assert ('nl', 'Dutch') in options.LANGUAGES
    assert ('na', 'Unknown / fallback') in options.LANGUAGES


@pytest.mark.parametrize('voice', ['M1', 'F5'])
def test_validates_supertonic_voices(voice):
    assert options.validate_voice(voice) == voice


@pytest.mark.parametrize('language', ['en', 'nl', 'na'])
def test_validates_supertonic_languages(language):
    assert options.validate_language(language) == language


def test_rejects_unknown_voice_and_language():
    with pytest.raises(ValueError, match='voice'):
        options.validate_voice('default')
    with pytest.raises(ValueError, match='language'):
        options.validate_language('xx')
