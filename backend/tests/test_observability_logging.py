import json
import logging

from app.core.observability import JsonFormatter


def test_json_formatter_includes_exception_class_and_traceback():
    try:
        raise RuntimeError("delivery failed")
    except RuntimeError:
        record = logging.getLogger(__name__).makeRecord(
            __name__, logging.ERROR, __file__, 10, "notification error", (),
            exc_info=__import__("sys").exc_info(),
        )

    payload = json.loads(JsonFormatter().format(record))

    assert payload["exception_class"] == "RuntimeError"
    assert "Traceback (most recent call last)" in payload["traceback"]
    assert "RuntimeError: delivery failed" in payload["traceback"]
