from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.security import OAuth2PasswordRequestForm

from app.core.security import create_access_token, verify_password
from app.dependencies import get_state, get_current_user
from app.schemas import Token, User
from app.state import AppState

router = APIRouter(prefix="/auth", tags=["auth"])


@router.post("/login", response_model=Token)
async def login(
    request: Request,
    form_data: OAuth2PasswordRequestForm = Depends(),
    state: AppState = Depends(get_state),
) -> Token:
    client_ip = request.client.host if request.client else "unknown"
    state.rate_limiter.check(f"login:{client_ip}", state.settings.login_rate_limit_per_minute)
    user_row = await state.user_repo.find_for_login(form_data.username)
    if user_row is None or not verify_password(form_data.password, user_row["password_hash"]):
        raise HTTPException(status_code=400, detail="Incorrect username or password")
    token = create_access_token({"sub": str(user_row["id"]), "role": user_row["role"]}, state.settings)
    return Token(access_token=token)


@router.get("/me", response_model=User)
async def me(current: User = Depends(get_current_user)) -> User:
    return current
