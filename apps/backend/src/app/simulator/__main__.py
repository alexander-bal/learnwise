import uvicorn

from app.core.config import get_settings
from app.core.logging import configure_logging


def main() -> None:
    settings = get_settings()
    configure_logging(settings.log_level)
    uvicorn.run(
        "app.simulator.main:app", host=settings.sim_host, port=settings.sim_port, log_config=None
    )


if __name__ == "__main__":
    main()
