"""Shared Chatterbox Turbo worker identity."""

ENGINE = 'Chatterbox Turbo (350M)'

DELIVERY_MODE_LABELS = (
    ('', 'Default (no tag)'),
    ('[angry]', '[angry] — Angry, forceful, frustrated'),
    ('[happy]', '[happy] — Upbeat, cheerful, energetic'),
    ('[crying]', '[crying] — Tearful, emotional, upset'),
    ('[fear]', '[fear] — Frightened, tense, nervous'),
    ('[surprised]', '[surprised] — Shocked, startled, amazed'),
    ('[sarcastic]', '[sarcastic] — Dry, ironic, sarcastic'),
    ('[dramatic]', '[dramatic] — Theatrical, intense, emphatic'),
    ('[whispering]', '[whispering] — Quiet, whispered delivery'),
    ('[narration]', '[narration] — Narrator / storytelling delivery'),
    (
        '[advertisement]',
        '[advertisement] — Polished commercial / promotional delivery',
    ),
)
DELIVERY_MODES = frozenset(mode for mode, _label in DELIVERY_MODE_LABELS)


def validate_delivery_mode(value):
    if not isinstance(value, str) or value not in DELIVERY_MODES:
        raise ValueError('invalid Turbo delivery mode')
    return value
