"""Public API, mounted at /v1. Paths have no trailing slash (as in the partner document)."""
from django.urls import path

from api_v1.booking import coverage
from api_v1.booking import views as booking
from api_v1.common.views import HealthView
from api_v1.instructions import views as instr
from api_v1.keys.views import MeView
from api_v1.payments import views as pay
from api_v1.tracking import views as track

urlpatterns = [
    path("health", HealthView.as_view()),
    path("me", MeView.as_view()),
    path("service-areas", coverage.ServiceAreasView.as_view()),
    path("quotes", booking.QuoteCreateView.as_view()),
    path("errands", booking.ErrandCreateView.as_view()),
    path("errands/<str:errand_id>", track.ErrandDetailView.as_view()),
    path("errands/<str:errand_id>/tracking", track.TrackingView.as_view()),
    path("errands/<str:errand_id>/public", track.PublicTrackingView.as_view()),
    path("errands/<str:errand_id>/dropoff", instr.DropoffView.as_view()),
    path("errands/<str:errand_id>/pickup", instr.PickupView.as_view()),
    path("errands/<str:errand_id>/checklist", instr.ChecklistAttachView.as_view()),
    path("errands/<str:errand_id>/tags", instr.TagsAttachView.as_view()),
    path("errands/<str:errand_id>/cancel", pay.CancelView.as_view()),
    path("checklists/generate", instr.ChecklistGenerateView.as_view()),
    path("wallet", pay.WalletView.as_view()),
]
