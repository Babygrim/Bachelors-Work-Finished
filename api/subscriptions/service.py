from datetime import datetime, timedelta, timezone

from ..core.errors import AppError, ErrorCode
from ..core.singleton import SingletonMeta
from ..core.store import InMemoryStore, Subscription, User

PLANS = {"free", "pro", "studio"}


class SubscriptionService(metaclass=SingletonMeta):
    def __init__(self) -> None:
        self.store = InMemoryStore()

    def get(self, user: User) -> Subscription:
        with self.store.lock:
            return self.store.subscriptions.setdefault(user.id, Subscription())

    def change_plan(self, user: User, plan: str) -> Subscription:
        if plan not in PLANS:
            raise AppError(
                ErrorCode.PLAN_NOT_FOUND,
                "The selected subscription plan is not available.",
                f"Choose one of: {', '.join(sorted(PLANS))}.",
                400,
            )
        subscription = self.get(user)
        subscription.plan = plan
        subscription.status = "active"
        subscription.renews_at = (
            None if plan == "free" else datetime.now(timezone.utc) + timedelta(days=30)
        )
        return subscription

    def cancel(self, user: User) -> Subscription:
        subscription = self.get(user)
        subscription.plan = "free"
        subscription.status = "cancelled"
        subscription.renews_at = None
        return subscription
