from app.core.config import Settings
from app.services.reviews import retry_delay


def test_the_wait_between_attempts_starts_at_a_minute_and_doubles_up_to_15() -> None:
    settings = Settings()
    assert [retry_delay(settings, n) for n in (1, 2, 3, 4, 5, 6)] == [
        60,
        120,
        240,
        480,
        900,
        900,
    ]
