from fastapi import Header

from ..auth.service import AuthService
from .store import User


def get_current_user(authorization: str | None = Header(default=None)) -> User:
    token = authorization.removeprefix("Bearer ").strip() if authorization else None
    return AuthService().user_from_token(token)
