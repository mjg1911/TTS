import logging

from piper.windows_tray.logging_setup import (
    log_capture_result,
    log_exception_safe,
)


def test_capture_log_contains_length_but_not_selected_text(caplog) -> None:
    secret = "BANK-PASSWORD-DO-NOT-LOG"
    logger = logging.getLogger("test.capture.redaction")

    with caplog.at_level(logging.INFO):
        log_capture_result(
            logger,
            outcome="SUCCESS",
            text_length=len(secret),
        )

    assert str(len(secret)) in caplog.text
    assert secret not in caplog.text


def test_safe_exception_log_drops_exception_message(caplog) -> None:
    secret = "SECRET-CAPTURED-TEXT"

    try:
        raise RuntimeError(secret)
    except RuntimeError as error:
        logger = logging.getLogger("test.exception.redaction")

        with caplog.at_level(logging.ERROR):
            log_exception_safe(
                logger,
                "speech failure",
                error,
                generation=4,
                phase="synthesis",
            )

    assert "RuntimeError" in caplog.text
    assert "generation=4" in caplog.text
    assert "phase=synthesis" in caplog.text
    assert secret not in caplog.text
