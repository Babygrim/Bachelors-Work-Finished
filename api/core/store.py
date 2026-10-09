from dataclasses import dataclass
from datetime import datetime
from threading import RLock

from .singleton import SingletonMeta


@dataclass
class User:
    id: str
    email: str
    password_hash: str


@dataclass
class Subscription:
    plan: str = "free"
    status: str = "active"
    renews_at: datetime | None = None


class InMemoryStore(metaclass=SingletonMeta):
    def __init__(self) -> None:
        if hasattr(self, "lock"):
            return
        self.lock = RLock()
        self.users_by_email: dict[str, User] = {}
        self.users_by_id: dict[str, User] = {}
        self.subscriptions: dict[str, Subscription] = {}
        self.tokens: dict[str, str] = {}
        self.jobs: dict[str, object] = {}
