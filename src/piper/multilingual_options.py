"""Lightweight options shared by the tray and Multilingual worker."""
import math
import numbers

ENGINE = 'Chatterbox Multilingual V3 (500M)'
SUPPORTED_LANGUAGES = {
    'ar': 'Arabic', 'da': 'Danish', 'de': 'German', 'el': 'Greek',
    'en': 'English', 'es': 'Spanish', 'fi': 'Finnish', 'fr': 'French',
    'he': 'Hebrew', 'hi': 'Hindi', 'it': 'Italian', 'ja': 'Japanese',
    'ko': 'Korean', 'ms': 'Malay', 'nl': 'Dutch', 'no': 'Norwegian',
    'pl': 'Polish', 'pt': 'Portuguese', 'ru': 'Russian', 'sv': 'Swedish',
    'sw': 'Swahili', 'tr': 'Turkish', 'zh': 'Chinese',
}


def validate_language(value):
    if not isinstance(value, str) or value not in SUPPORTED_LANGUAGES:
        raise ValueError('Select a supported Multilingual language.')
    return value


def _validate_number(value, low, high, label):
    if isinstance(value, bool) or not isinstance(value, numbers.Real):
        raise ValueError(f'{label} must be a finite number.')
    value = float(value)
    if not math.isfinite(value) or not low <= value <= high:
        raise ValueError(f'{label} must be between {low:g} and {high:g}.')
    return value


def validate_exaggeration(value):
    return _validate_number(value, 0.25, 2.0, 'Expressiveness')


def validate_cfg_weight(value):
    return _validate_number(value, 0.0, 1.0, 'Voice/style guidance')
