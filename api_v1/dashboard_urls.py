"""Browser (signed-in) endpoints for the Developers page, mounted at /dashboard."""
from django.urls import path

from api_v1.common.views import LoginView, LogoutView
from api_v1.keys import views as keys
from api_v1.notices import views as notices
from api_v1.payments.views import DashboardWalletView
from api_v1.reliability import views as hooks

urlpatterns = [
    path("login", LoginView.as_view()),
    path("logout", LogoutView.as_view()),
    path("api-keys", keys.KeyListCreateView.as_view()),
    path("api-keys/<str:key_id>", keys.KeyRevokeView.as_view()),
    path("webhook-endpoints", hooks.WebhookEndpointListCreateView.as_view()),
    path("webhook-endpoints/<str:endpoint_id>", hooks.WebhookEndpointDeleteView.as_view()),
    path("notifications", notices.NotificationListView.as_view()),
    path("notifications/<str:notification_id>/read", notices.NotificationReadView.as_view()),
    path("wallet", DashboardWalletView.as_view()),
]
