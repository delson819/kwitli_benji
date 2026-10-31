from fastapi import APIRouter, Depends, HTTPException

from backend.app.dependencies import get_current_user
from backend.app.persistence.models import User
from backend.app.schemas.users import UserResponse

router = APIRouter(prefix="/users", tags=["users"])


@router.get("/{user_id}", response_model=UserResponse)
def get_user(
    user_id: str,
    current_user: User = Depends(get_current_user),
) -> UserResponse:
    if current_user.id != user_id:
        raise HTTPException(status_code=404, detail="Utilisateur introuvable.")
    return current_user
