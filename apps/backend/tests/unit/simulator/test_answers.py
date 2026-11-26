from app.simulator.answers import classify

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
