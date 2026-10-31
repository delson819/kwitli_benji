from fastapi import APIRouter, Depends, Response
from sqlalchemy.orm import Session

from backend.app.core.config import get_settings
from backend.app.core.service_areas import ServiceArea, public_service_area
from backend.app.database import get_db_session
from backend.app.repositories.service_areas import SqlAlchemyServiceAreaRepository

router = APIRouter(prefix="/service-areas", tags=["service areas"])


@router.get("", response_model=list[ServiceArea])
def get_service_areas(
    response: Response,
    session: Session = Depends(get_db_session),
) -> list[ServiceArea]:
    response.headers["Cache-Control"] = "no-store"
    areas = SqlAlchemyServiceAreaRepository(session).list_for_environment(
        get_settings().app_env, active_only=True
    )
    return [public_service_area(area) for area in areas if area.geometry_type == "circle"]
