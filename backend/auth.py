import os
import hashlib
from datetime import datetime, timedelta
from typing import Optional

from jose import JWTError, jwt
from passlib.context import CryptContext

SECRET_KEY: str = os.getenv("SECRET_KEY", "change-me-in-production-32-chars!!")
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_DAYS = 7

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")


def hash_password(password: str) -> str:
    return pwd_context.hash(password)


def verify_password(plain: str, hashed: str) -> bool:
    """Verify against bcrypt hash. Falls back to legacy SHA-256 for migration."""
    if hashed and hashed.startswith("$2"):
        return pwd_context.verify(plain, hashed)
    # Legacy SHA-256 from old Streamlit app
    return hashlib.sha256(plain.encode()).hexdigest() == hashed


def create_access_token(tenant_id: int, email: str) -> str:
    payload = {
        "tenant_id": tenant_id,
        "email": email,
        "exp": datetime.utcnow() + timedelta(days=ACCESS_TOKEN_EXPIRE_DAYS),
    }
    return jwt.encode(payload, SECRET_KEY, algorithm=ALGORITHM)


def decode_jwt(token: str) -> Optional[dict]:
    try:
        return jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
    except JWTError:
        return None
