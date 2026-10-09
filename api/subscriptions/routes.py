from fastapi import APIRouter, Depends
from pydantic import BaseModel

from ..core.dependencies import get_current_user
from ..core.schemas import SubscriptionResponse
from ..core.store import User
from .service import SubscriptionService

router = APIRouter(prefix="/api/subscription", tags=["subscription"])


class ChangePlanRequest(BaseModel):
    plan: str


def _response(user: User) -> SubscriptionResponse:
    subscription = SubscriptionService().get(user)
    return SubscriptionResponse(
        plan=subscription.plan,
        status=subscription.status,
        renews_at=subscription.renews_at,
        payments_enabled=False,
    )


@router.get("", response_model=SubscriptionResponse)
def get_subscription(user: User = Depends(get_current_user)) -> SubscriptionResponse:
    return _response(user)


@router.post("/change", response_model=SubscriptionResponse)
def change_subscription(
    request: ChangePlanRequest, user: User = Depends(get_current_user)
) -> SubscriptionResponse:
    SubscriptionService().change_plan(user, request.plan)
    return _response(user)


@router.post("/cancel", response_model=SubscriptionResponse)
def cancel_subscription(user: User = Depends(get_current_user)) -> SubscriptionResponse:
    SubscriptionService().cancel(user)
    return _response(user)
