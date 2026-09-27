import pytest

from piper.windows_tray.sentence_splitter import split_speech_sentences


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        (
            "First sentence. Second sentence? Third sentence!",
            ("First sentence.", "Second sentence?", "Third sentence!"),
        ),
        (
            "The value is 3.14 volts. Continue reading.",
            ("The value is 3.14 volts.", "Continue reading."),
        ),
        (
            "Dr. Smith met Mr. Jones. They left together.",
            ("Dr. Smith met Mr. Jones.", "They left together."),
        ),
        (
            "Use examples, e.g. apples and pears. Then continue.",
            ("Use examples, e.g. apples and pears.", "Then continue."),
        ),
        (
            "The U.S. team arrived. Next stop!",
            ("The U.S. team arrived.", "Next stop!"),
        ),
        (
            'She said "Go now." Then we left.',
            ('She said "Go now."', "Then we left."),
        ),
        (
            "Wait... Then continue.",
            ("Wait...", "Then continue."),
        ),
        (
            "A final fragment without punctuation",
            ("A final fragment without punctuation",),
        ),
    ],
)
def test_split_speech_sentences(text, expected):
    assert split_speech_sentences(text) == expected


def test_split_speech_sentences_ignores_blank_text():
    assert split_speech_sentences("  \n\t") == ()
