from fastapi import APIRouter, Depends

from ..core.dependencies import get_current_user
from ..core.schemas import AuthResponse, LoginRequest, RegisterRequest, UserResponse
from ..core.store import User
from ..subscriptions.service import SubscriptionService
from .service import AuthService

router = APIRouter(prefix="/api/auth", tags=["auth"])


def _user_response(user: User) -> UserResponse:
    return UserResponse(
        id=user.id,
        email=user.email,
        subscription=SubscriptionService().get(user).plan,
    )


@router.post("/register", response_model=AuthResponse, status_code=201)
def register(request: RegisterRequest) -> AuthResponse:
    user, token = AuthService().register(request.email, request.password)
    return AuthResponse(access_token=token, user=_user_response(user))


@router.post("/login", response_model=AuthResponse)
def login(request: LoginRequest) -> AuthResponse:
    user, token = AuthService().authenticate(request.email, request.password)
    return AuthResponse(access_token=token, user=_user_response(user))


@router.get("/me", response_model=UserResponse)
def me(user: User = Depends(get_current_user)) -> UserResponse:
    return _user_response(user)
