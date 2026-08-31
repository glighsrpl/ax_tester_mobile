import inspect
import logging
from typing import Any

import litellm


class CallerRefFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        if hasattr(record, "caller_filename"):
            record.filename = record.caller_filename
            record.lineno = record.caller_lineno
        return True


class CallerAdapter(logging.LoggerAdapter):
    def process(self, msg: str, kwargs: dict) -> tuple[str, dict]:
        frame = inspect.currentframe()
        try:
            caller = inspect.stack()[4]
            module_name = caller.frame.f_globals.get("__name__", "unknown")
            kwargs.setdefault("extra", {})
            kwargs["extra"]["caller_filename"] = f"{module_name.split('.')[-1]}.py"
            kwargs["extra"]["caller_lineno"] = caller.lineno
        except IndexError:
            pass
        finally:
            del frame
        return msg, kwargs


def _get_caller_logger() -> CallerAdapter:
    frame = inspect.currentframe()
    try:
        if frame is None or frame.f_back is None or frame.f_back.f_back is None:
            return CallerAdapter(logging.getLogger("unknown"), {})
        caller_frame = frame.f_back.f_back.f_back
        module_name = caller_frame.f_globals.get("__name__", "unknown")
        base_logger = logging.getLogger(module_name.split(".")[-1])
        if not any(isinstance(f, CallerRefFilter) for f in base_logger.filters):
            base_logger.addFilter(CallerRefFilter())
        return CallerAdapter(base_logger, {})
    finally:
        del frame


def call_llm(model: str, temperature: float, messages: list[dict[str, Any]]) -> str:
    caller_logger = _get_caller_logger()
    caller_logger.info(f"Calling LiteLLM with model={model}")

    resp = litellm.completion(
        model=model,
        messages=messages,
        temperature=temperature,
    )

    if isinstance(resp, str):
        return resp
    if hasattr(resp, "choices") and resp.choices:
        choice = resp.choices[0]
        if hasattr(choice, "message") and isinstance(choice.message, dict):
            return choice.message.get("content", "")
        if hasattr(choice, "message") and hasattr(choice.message, "content"):
            return choice.message.content
        if hasattr(choice, "text"):
            return choice.text
    if isinstance(resp, dict):
        choices = resp.get("choices") or []
        if choices:
            message = choices[0].get("message") or {}
            return message.get("content", "") or choices[0].get("text", "")
    return ""
