from fastapi import Depends, HTTPException, Request
from fastapi.security import OAuth2PasswordBearer
from jose import JWTError, jwt

from app.schemas import User
from app.state import AppState

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/auth/login")


def get_state(request: Request) -> AppState:
    return request.app.state.container


async def get_current_user(
    token: str = Depends(oauth2_scheme),
    state: AppState = Depends(get_state),
) -> User:
    credentials_exception = HTTPException(
        status_code=401,
        detail="Could not validate credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )
    try:
        payload = jwt.decode(
            token,
            state.settings.auth_secret_key,
            algorithms=[state.settings.auth_algorithm],
        )
        user_id: str = payload.get("sub")
        role: str = payload.get("role")
        if user_id is None or role is None:
            raise credentials_exception
    except JWTError as exc:
        raise credentials_exception from exc

    row = await state.user_repo.find_by_id(int(user_id))
    if row is None:
        raise credentials_exception
    return User(id=row["id"], username=row["username"], role=row["role"])


async def require_reader(user: User = Depends(get_current_user)) -> User:
    if user.role not in ("reader", "admin"):
        raise HTTPException(status_code=403, detail="Insufficient permissions")
    return user


async def require_admin(user: User = Depends(get_current_user)) -> User:
    if user.role != "admin":
        raise HTTPException(status_code=403, detail="Admin role required")
    return user
