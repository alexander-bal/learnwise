import json

from app.simulator.answers import answer, classify

PROMPT = "intent: billing, shipping, technical_issue, or other"


def test_the_first_intent_in_the_message_that_the_prompt_names_wins() -> None:
    assert classify("shipping then billing", PROMPT, model="fake")["intent"] == "shipping"
    assert (
        classify("A Technical Issue at login", PROMPT, model="fake")["intent"] == "technical_issue"
    )


def test_an_intent_the_prompt_does_not_name_is_other_except_for_the_judge() -> None:
    assert classify("my account is locked", PROMPT, model="fake")["intent"] == "other"
    assert classify("my account is locked", PROMPT, model="fake-judge")["intent"] == "account"


def test_urgency_is_high_on_urgent_or_asap() -> None:
    assert classify("URGENT billing", PROMPT, model="fake")["urgency"] == "high"
    assert classify("billing asap", PROMPT, model="fake")["urgency"] == "high"
    assert classify("billing", PROMPT, model="fake")["urgency"] == "normal"


SEEDED = "intent: billing, shipping, technical_issue, or other when none of these fits."
JUDGE_SCHEMA = {"properties": {"record": {}, "explanation": {}}}
PROPOSAL_SCHEMA = {"properties": {"prompt": {}, "reason": {}}}


def test_the_judge_returns_the_record_it_recognises_for_the_message() -> None:
    content = json.dumps({"message": "my cancellation ASAP", "output": {"intent": "other"}})
    verdict = answer("fake-judge", "judge", content, JUDGE_SCHEMA, harmful=False)
    assert verdict["record"] == {"intent": "cancellation", "urgency": "high"}  # ty: ignore
    assert verdict["explanation"]  # ty: ignore


def test_the_proposal_names_the_intents_among_the_errors_shown() -> None:
    content = json.dumps(
        {
            "prompt": SEEDED,
            "errors": [{"message": "m", "output": {}, "expected": {"intent": "cancellation"}}],
        }
    )
    proposal = answer("fake-judge", "propose", content, PROPOSAL_SCHEMA, harmful=False)
    new_prompt = proposal["prompt"]  # ty: ignore
    assert new_prompt.startswith(SEEDED)
    assert classify("my cancellation", new_prompt, model="fake")["intent"] == "cancellation"
    assert classify("my account", new_prompt, model="fake")["intent"] == "other"
    assert classify("billing", new_prompt, model="fake")["intent"] == "billing"


def test_a_harmful_proposal_names_no_intent() -> None:
    content = json.dumps({"prompt": SEEDED, "errors": []})
    proposal = answer("fake-judge", "propose", content, PROPOSAL_SCHEMA, harmful=True)
    new_prompt = proposal["prompt"]  # ty: ignore
    assert new_prompt != SEEDED
    for message in ("billing", "shipping", "a technical issue"):
        assert classify(message, new_prompt, model="fake")["intent"] == "other"


def test_the_processing_model_still_triages() -> None:
    assert answer("fake", SEEDED, "billing", {}, harmful=True) == {
        "intent": "billing",
        "urgency": "normal",
    }
