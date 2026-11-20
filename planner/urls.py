from django.urls import path

from planner import views

urlpatterns = [
    path("trip-plans", views.TripPlanCreateView.as_view(), name="trip-plan-create"),
    path("trip-plans/<uuid:plan_id>", views.TripPlanDetailView.as_view(), name="trip-plan"),
    path("trip-plans/<uuid:plan_id>/map", views.trip_plan_map, name="trip-plan-map"),
]
