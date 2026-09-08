from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from sqlalchemy.orm import Session as DBSession

from app.database import get_db
from app.models import AuthSession, User
from app.security import decode_token

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="auth/login")


def get_current_session(
    token: str = Depends(oauth2_scheme), db: DBSession = Depends(get_db)
) -> AuthSession:
    payload = decode_token(token)
    if payload is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid or expired token")

    jti = payload.get("jti")
    auth_session = db.query(AuthSession).filter(AuthSession.jti == jti).first()
    if auth_session is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Unknown session")
    if auth_session.status == "terminated":
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Session terminated by risk engine")
    if auth_session.status == "logged_out":
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Session ended")

    return auth_session


def get_current_user(
    auth_session: AuthSession = Depends(get_current_session), db: DBSession = Depends(get_db)
) -> User:
    user = db.query(User).filter(User.id == auth_session.user_id).first()
    if user is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "User not found")
    return user
