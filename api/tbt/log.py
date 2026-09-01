import logging

from .config import settings


def configure_logging() -> None:
    root = logging.getLogger()
    if not root.handlers:
        logging.basicConfig(
            level=getattr(logging, settings.log_level, logging.INFO),
            format="%(asctime)s %(levelname)s %(name)s %(message)s",
        )
    else:
        root.setLevel(getattr(logging, settings.log_level, logging.INFO))
