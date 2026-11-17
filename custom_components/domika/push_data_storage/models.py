"""Push data models."""
from dataclasses import dataclass, field


@dataclass
class PushData:
    event_id: str
    app_session_id: str
    # Authorizes pushes to a phone; kept out of the repr and thus out of logs.
    push_session_id: str = field(repr=False)
    entity_id: str
    attribute: str
    value: str
    context_id: str
    timestamp: int
    delay: int
