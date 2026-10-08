"""Shared Supertonic 3 engine and voice configuration."""

ENGINE = 'Supertonic 3'
DEFAULT_VOICE = 'M1'
DEFAULT_LANGUAGE = 'en'
DEFAULT_DEVICE = 'cuda'


def validate_device(value):
    """Return an explicitly supported execution device."""
    if not isinstance(value, str) or value not in ('cpu', 'cuda'):
        raise ValueError(f'unsupported Supertonic 3 device: {value!r}; choose CPU or GPU (CUDA)')
    return value

VOICES = tuple(
    (f'{gender}{number}', f'{gender}{number} — {gender_label} {number}')
    for gender, gender_label in (('M', 'Male'), ('F', 'Female'))
    for number in range(1, 6)
)

LANGUAGES = (
    ('en', 'English'),
    ('ko', 'Korean'),
    ('ja', 'Japanese'),
    ('ar', 'Arabic'),
    ('bg', 'Bulgarian'),
    ('cs', 'Czech'),
    ('da', 'Danish'),
    ('de', 'German'),
    ('el', 'Greek'),
    ('es', 'Spanish'),
    ('et', 'Estonian'),
    ('fi', 'Finnish'),
    ('fr', 'French'),
    ('hi', 'Hindi'),
    ('hr', 'Croatian'),
    ('hu', 'Hungarian'),
    ('id', 'Indonesian'),
    ('it', 'Italian'),
    ('lt', 'Lithuanian'),
    ('lv', 'Latvian'),
    ('nl', 'Dutch'),
    ('pl', 'Polish'),
    ('pt', 'Portuguese'),
    ('ro', 'Romanian'),
    ('ru', 'Russian'),
    ('sk', 'Slovak'),
    ('sl', 'Slovenian'),
    ('sv', 'Swedish'),
    ('tr', 'Turkish'),
    ('uk', 'Ukrainian'),
    ('vi', 'Vietnamese'),
    ('na', 'Unknown / fallback'),
)

_VOICE_CODES = frozenset(code for code, _label in VOICES)
_LANGUAGE_CODES = frozenset(code for code, _label in LANGUAGES)


def validate_voice(value):
    """Return a supported built-in voice code."""
    if not isinstance(value, str) or value not in _VOICE_CODES:
        raise ValueError(f'unsupported Supertonic 3 voice: {value!r}')
    return value


def validate_language(value):
    """Return a supported ISO language code or the SDK's ``na`` fallback."""
    if not isinstance(value, str) or value not in _LANGUAGE_CODES:
        raise ValueError(f'unsupported Supertonic 3 language: {value!r}')
    return value
