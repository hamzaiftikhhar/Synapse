"""Django Ninja API entrypoint — mounts all v1 routers."""

from django.conf import settings
from ninja import NinjaAPI

from apps.api.analytics.router import router as analytics_router
from apps.api.applications.router import router as applications_router
from apps.api.appointments.router import router as appointments_router
from apps.api.billing.router import router as billing_router
from apps.api.auth.patient_router import router as patient_auth_router
from apps.api.widget.router import router as widget_public_router
from apps.api.widget.booking_router import router as widget_booking_router
from apps.api.auth.router import router as auth_router
from apps.api.chat.router import router as chat_router
from apps.api.clinics.router import router as clinics_router
from apps.api.doctors.router import router as doctors_router
from apps.api.importer.router import router as importer_router
from apps.api.insurance.router import router as insurance_router
from apps.api.knowledge.router import router as knowledge_router
from apps.api.patients.router import router as patients_router
from apps.api.platform.router import router as platform_router
from apps.api.services.router import router as services_router
from apps.api.specialties.router import router as specialties_router

api = NinjaAPI(
    title="Synapse API",
    version="1.0.0",
    description=(
        "Multi-tenant Healthcare AI Chatbot SaaS.\n\n"
        "**Staff auth** (portal): POST /auth/login with email+password → "
        "staff_access + staff_refresh JWTs. Use Authorization: Bearer on /patients, "
        "/doctors, etc.\n\n"
        "**Patient auth** (widget): POST /widget/otp/send + /widget/otp/verify → "
        "short-lived patient_access JWT. Independent from staff accounts."
    ),
    docs_url="/docs",
    openapi_url="/openapi.json",
)

api.add_router("/auth", auth_router)
api.add_router("/platform", platform_router)
api.add_router("/widget", patient_auth_router)
api.add_router("/widget", widget_public_router)
api.add_router("/widget", widget_booking_router)
api.add_router("/chat", chat_router)
api.add_router("/documents", knowledge_router)
api.add_router("/patients", patients_router)
api.add_router("/clinics", clinics_router)
api.add_router("/doctors", doctors_router)
api.add_router("/services", services_router)
api.add_router("/specialties", specialties_router)
api.add_router("/insurance", insurance_router)
api.add_router("/import", importer_router)
api.add_router("/appointments", appointments_router)
api.add_router("/billing", billing_router)
api.add_router("/analytics", analytics_router)
api.add_router("/applications", applications_router)

if settings.DEBUG:
    from apps.api.debug.router import router as debug_router

    api.add_router("/debug", debug_router)
