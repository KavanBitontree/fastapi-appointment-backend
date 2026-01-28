from datetime import datetime, timedelta, timezone
from jose import jwt
from argon2 import PasswordHasher, exceptions as argon2_exceptions
from core.config import settings

# --- Password hashing using Argon2 ---
ph = PasswordHasher()

def hash_password(password: str) -> str:
    """
    Hash a plain password with Argon2.
    """
    return ph.hash(password)

def verify_password(password: str, hashed: str) -> bool:
    """
    Verify a password against a stored hash.
    """
    try:
        return ph.verify(hashed, password)
    except argon2_exceptions.VerifyMismatchError:
        return False
    except argon2_exceptions.VerificationError:
        return False

# --- JWT token utilities ---
def create_access_token(data: dict, expires_minutes: int | None = None) -> str:
    """
    Create a JWT access token.
    """
    if expires_minutes is None:
        expires_minutes = settings.ACCESS_TOKEN_EXPIRE_MINUTES

    to_encode = data.copy()
    expire = datetime.now(timezone.utc) + timedelta(minutes=expires_minutes)
    to_encode.update({"exp": expire})

    return jwt.encode(
        to_encode,
        settings.JWT_SECRET_KEY,
        algorithm=settings.JWT_ALGORITHM,
    )

def decode_access_token(token: str) -> dict:
    """
    Decode a JWT token and return its payload.
    """
    try:
        payload = jwt.decode(
            token,
            settings.JWT_SECRET_KEY,
            algorithms=[settings.JWT_ALGORITHM],
        )
        return payload
    except jwt.ExpiredSignatureError:
        raise ValueError("Token has expired")
    except jwt.JWTError:
        raise ValueError("Invalid token")
