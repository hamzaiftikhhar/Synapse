"""Django Ninja API entrypoint — mounts all v1 routers."""

from ninja import NinjaAPI

from apps.api.appointments.router import router as appointments_router
from apps.api.auth.router import router as auth_router
from apps.api.doctors.router import router as doctors_router
from apps.api.patients.router import router as patients_router
from apps.api.services.router import router as services_router

api = NinjaAPI(
    title="Synapse API",
    version="1.0.0",
    description=(
        "Multi-tenant Healthcare AI Chatbot — clinic dashboard API. "
        "Authenticate via POST /auth/login, then pass "
        "`Authorization: Bearer <token>` on all other requests."
    ),
    docs_url="/docs",
    openapi_url="/openapi.json",
)

api.add_router("/auth", auth_router)
api.add_router("/patients", patients_router)
api.add_router("/doctors", doctors_router)
api.add_router("/services", services_router)
api.add_router("/appointments", appointments_router)
