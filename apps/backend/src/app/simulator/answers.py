"""How the simulator answers (docs/simulator.md, "How it answers")."""

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
