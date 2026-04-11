import datetime
from typing import Final

TIMEZONE: Final = datetime.timezone.utc


def get_chat_timestamp() -> datetime.datetime:
    return datetime.datetime.now(TIMEZONE)
