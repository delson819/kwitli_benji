from fastapi import APIRouter

from backend.app.api.routes import auth, availabilities, business_hours, cooks, discover, dishes, favorites, health, kyb, orders, payments, reviews, service_areas, users

api_router = APIRouter()
api_router.include_router(health.router)
api_router.include_router(auth.router)
api_router.include_router(users.router)
api_router.include_router(cooks.router)
api_router.include_router(business_hours.router)
api_router.include_router(dishes.router)
api_router.include_router(availabilities.router)
api_router.include_router(orders.router)
api_router.include_router(payments.router)
api_router.include_router(reviews.router)
api_router.include_router(favorites.router)
api_router.include_router(discover.router)
api_router.include_router(service_areas.router)
api_router.include_router(kyb.router)
