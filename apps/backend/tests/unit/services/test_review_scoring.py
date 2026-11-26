from app.services.reviews import Judged, errors_to_show, points, score

BASE, CAND = 1, 2


def row(sample: str, version: int, output: dict | None, expected: dict | None, judged=True):
    return Judged(sample, version, output, expected, judged)


def rec(intent: str, urgency: str = "normal") -> dict[str, str]:
    return {"intent": intent, "urgency": urgency}


def test_points_count_fields_equal_to_the_rows_own_judgment() -> None:
    assert points(row("s", BASE, rec("billing"), rec("billing"))) == 2
    assert points(row("s", BASE, rec("other"), rec("cancellation"))) == 1
    assert points(row("s", BASE, rec("other", "high"), rec("billing"))) == 0
    assert points(row("s", CAND, None, None, judged=False)) == 0


def test_an_output_is_in_error_only_when_judged_and_different() -> None:
    assert row("s", BASE, rec("other"), rec("billing")).in_error
    assert not row("s", BASE, rec("billing"), rec("billing")).in_error
    assert not row("s", BASE, rec("other"), None).in_error  # unjudgeable
    assert not row("s", BASE, rec("other"), None, judged=False).in_error


def test_a_sample_with_an_unjudgeable_output_is_left_out_of_both_scores() -> None:
    rows = [
        row("a", BASE, rec("billing"), rec("billing")),
        row("a", CAND, rec("billing"), rec("billing")),
        row("b", BASE, rec("other"), None),  # unjudgeable base
        row("b", CAND, rec("billing"), rec("billing")),
        row("c", BASE, rec("other"), rec("cancellation")),
        row("c", CAND, rec("cancellation"), None),  # unjudgeable candidate
    ]
    result = score(rows, BASE, CAND)
    assert (result.base, result.candidate, result.counted, result.left_out) == (2, 2, 1, 2)


def test_a_missing_candidate_output_scores_zero_but_counts() -> None:
    rows = [
        row("a", BASE, rec("billing"), rec("billing")),
        row("a", CAND, None, None, judged=False),
    ]
    result = score(rows, BASE, CAND)
    assert (result.base, result.candidate, result.counted) == (2, 0, 1)


def test_without_a_candidate_only_the_base_is_scored() -> None:
    result = score([row("a", BASE, rec("billing"), rec("billing"))], BASE, None)
    assert (result.base, result.candidate) == (2, None)


def test_errors_are_shown_most_recent_first_while_their_messages_fit() -> None:
    a, b, c = (row(s, BASE, rec("other"), rec("account")) for s in "abc")
    errors = [("x" * 4000, a), ("y" * 4000, b), ("z" * 10, c)]
    assert errors_to_show(errors, 6000) == [errors[0]]
    assert errors_to_show(errors[1:], 6000) == errors[1:]
    assert errors_to_show(errors, 8000) == errors[:2]
