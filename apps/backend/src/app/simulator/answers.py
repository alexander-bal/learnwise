"""How the simulator answers (docs/simulator.md, "How it answers")."""

import json
import re

INTENTS = ("billing", "shipping", "technical_issue", "account", "cancellation")
PROCESSING_MODEL = "fake"
JUDGE_MODEL = "fake-judge"
MODELS = (PROCESSING_MODEL, JUDGE_MODEL)


def _pattern(intent: str) -> re.Pattern[str]:
    return re.compile(re.escape(intent.replace("_", " ")), re.IGNORECASE)


def _normalise(text: str) -> str:
    return text.replace("_", " ")


def classify(message: str, prompt: str, *, model: str) -> dict[str, str]:
    """The record for a message: the first intent named in it that the prompt names too.

    The judge recognises every intent, whatever the prompt names.
    """
    text = _normalise(message)
    known = (
        INTENTS
        if model == JUDGE_MODEL
        else tuple(i for i in INTENTS if _pattern(i).search(_normalise(prompt)))
    )
    found = [(m.start(), i) for i in known if (m := _pattern(i).search(text))]
    intent = min(found)[1] if found else "other"
    urgency = "high" if re.search(r"urgent|asap", message, re.IGNORECASE) else "normal"
    return {"intent": intent, "urgency": urgency}


def count_tokens(text: str) -> int:
    return max(1, len(text.split()))


def _named(intents: list[str]) -> str:
    return ", ".join(intents)


def judge(content: str) -> dict[str, object]:
    """The judge's verdict: the record it recognises in the message, whatever the output.

    The content is the review's delimited data, `{"message": ..., "output": ...}`.
    """
    try:
        data = json.loads(content)
        message = str(data["message"])
    except ValueError, KeyError, TypeError:
        message = content
    record = classify(message, "", model=JUDGE_MODEL)
    return {"record": record, "explanation": f"The message is about {record['intent']}."}


def propose(content: str, *, harmful: bool) -> dict[str, str]:
    """A new prompt: the base prompt naming each intent among the errors it was shown.

    The content is `{"prompt": ..., "errors": [{"message", "output", "expected"}, ...]}`. A
    harmful proposal drops every intent the base prompt names and adds none.
    """
    data = json.loads(content)
    base = str(data["prompt"])
    if harmful:
        stripped = _normalise(base)
        for intent in INTENTS:
            stripped = _pattern(intent).sub("", stripped)
        return {"prompt": stripped, "reason": "Removed the intent list."}
    shown = {e["expected"]["intent"] for e in data.get("errors", [])}
    missing = [i for i in INTENTS if i in shown and not _pattern(i).search(_normalise(base))]
    if not missing:
        return {"prompt": base, "reason": "Nothing to add."}
    return {
        "prompt": f"{base}\n\nintent may also be: {_named(missing)}.",
        "reason": f"Messages about {_named(missing)} were classified as other.",
    }


def answer(model: str, prompt: str, content: str, schema: object, *, harmful: bool) -> object:
    """The answer for a chat call: triage for the processing model; for the judge, a
    proposal when the output schema asks for a prompt, else a verdict."""
    if model != JUDGE_MODEL:
        return classify(content, prompt, model=model)
    properties = schema.get("properties", {}) if isinstance(schema, dict) else {}
    if "prompt" in properties:
        return propose(content, harmful=harmful)
    if "record" in properties:
        return judge(content)
    return classify(content, prompt, model=model)
