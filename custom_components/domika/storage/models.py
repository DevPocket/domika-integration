"""Storage models."""
from collections import namedtuple
from dataclasses import dataclass, field
from datetime import datetime

UsersData = namedtuple('UsersData', 'value value_hash')


# Push session ids and push token hashes act as credentials, so models keep them out of their repr and the logs.
@dataclass
class Sessions:
    app_session_id: str
    push_session_id: str = field(repr=False)


@dataclass
class AppSession:
    id: str
    user_id: str
    push_session_id: str = field(repr=False)
    last_update: datetime
    push_token_hash: str = field(repr=False)

    @staticmethod
    def init_from_dict(app_session_id: str, d: dict):
        return AppSession(
            id=app_session_id,
            user_id=d.get("user_id"),
            push_session_id=d.get("push_session_id"),
            last_update=d.get("last_update"),
            push_token_hash=d.get("push_token_hash")
        )


@dataclass
class Subscription:
    app_session_id: str
    entity_id: str
    attribute: str
    need_push: bool
