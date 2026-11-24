from django.urls import path

from . import views

urlpatterns = [
    path("", views.index),
    path("track/<str:errand_id>", views.track_page),
    path("portal/assets/<str:name>", views.asset),
    path("portal/simulate/<str:errand_id>", views.SimulateView.as_view()),
]
