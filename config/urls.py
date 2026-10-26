from django.urls import include, path

urlpatterns = [
    path("v1/", include("api_v1.urls")),
    path("dashboard/", include("api_v1.dashboard_urls")),
]
