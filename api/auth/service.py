import hashlib
import hmac
import secrets
from uuid import uuid4

from ..core.errors import AppError, ErrorCode
from ..core.singleton import SingletonMeta
from ..core.store import InMemoryStore, User


class AuthService(metaclass=SingletonMeta):
    def __init__(self) -> None:
        self.store = InMemoryStore()

    @staticmethod
    def _normalize_email(email: str) -> str:
        return email.strip().lower()

    @staticmethod
    def _hash_password(password: str) -> str:
        salt = secrets.token_bytes(16)
        digest = hashlib.pbkdf2_hmac("sha256", password.encode(), salt, 120_000)
        return f"{salt.hex()}${digest.hex()}"

    @staticmethod
    def _verify_password(password: str, stored_hash: str) -> bool:
        salt_hex, digest_hex = stored_hash.split("$", 1)
        digest = hashlib.pbkdf2_hmac(
            "sha256", password.encode(), bytes.fromhex(salt_hex), 120_000
        )
        return hmac.compare_digest(digest.hex(), digest_hex)

    def register(self, email: str, password: str) -> tuple[User, str]:
        normalized_email = self._normalize_email(email)
        with self.store.lock:
            if normalized_email in self.store.users_by_email:
                raise AppError(
                    ErrorCode.USER_EXISTS,
                    "An account with this email already exists.",
                    "The email is already registered.",
                    409,
                )
            user = User(str(uuid4()), normalized_email, self._hash_password(password))
            self.store.users_by_email[normalized_email] = user
            self.store.users_by_id[user.id] = user
            token = self._issue_token(user)
            return user, token

    def authenticate(self, email: str, password: str) -> tuple[User, str]:
        normalized_email = self._normalize_email(email)
        with self.store.lock:
            user = self.store.users_by_email.get(normalized_email)
            if user is None or not self._verify_password(password, user.password_hash):
                raise AppError(
                    ErrorCode.INVALID_CREDENTIALS,
                    "Email or password is incorrect.",
                    "The supplied credentials do not match an account.",
                    401,
                )
            return user, self._issue_token(user)

    def _issue_token(self, user: User) -> str:
        token = secrets.token_urlsafe(32)
        self.store.tokens[token] = user.id
        return token

    def user_from_token(self, token: str | None) -> User:
        if not token:
            raise AppError(
                ErrorCode.UNAUTHORIZED,
                "Authentication is required.",
                "Provide a bearer access token.",
                401,
            )
        user_id = self.store.tokens.get(token)
        user = self.store.users_by_id.get(user_id or "")
        if user is None:
            raise AppError(
                ErrorCode.INVALID_TOKEN,
                "The access token is invalid.",
                "Sign in again to obtain a new access token.",
                401,
            )
        return user
