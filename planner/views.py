import logging

from django.shortcuts import get_object_or_404, render
from django.urls import reverse
from drf_spectacular.utils import OpenApiExample, OpenApiResponse, extend_schema
from rest_framework import status
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from geo.places import OutsideUSA, PlaceNotFound
from planner.models import TripPlan
from planner.optimizer import NoFuelInRange
from planner.serializers import ErrorSerializer, TripPlanSerializer, TripRequestSerializer
from planner.service import SamePlace, TripRequest, plan_trip
from routing.providers import NoRouteFound, RoutingError

logger = logging.getLogger(__name__)

ERRORS = {
    404: OpenApiResponse(ErrorSerializer, description="Start or finish not found"),
    422: OpenApiResponse(ErrorSerializer, description="Outside the USA, no route, or no fuel"),
    502: OpenApiResponse(ErrorSerializer, description="The routing provider failed"),
}


def error(code: str, detail, http_status: int) -> Response:
    return Response({"error": code, "detail": detail}, status=http_status)


def with_links(request: Request, plan: TripPlan) -> dict:
    map_url = request.build_absolute_uri(reverse("trip-plan-map", args=[plan.id]))
    return {"id": str(plan.id), "map_url": map_url, **plan.result}


class TripPlanCreateView(APIView):
    """Plan a trip and its cheapest fuel stops."""

    @extend_schema(
        request=TripRequestSerializer,
        responses={201: TripPlanSerializer, 400: ErrorSerializer, **ERRORS},
        examples=[
            OpenApiExample(
                "Denver to Chicago",
                value={"start": "Denver, CO", "finish": "Chicago, IL"},
                request_only=True,
            )
        ],
        summary="Plan a trip with fuel stops",
    )
    def post(self, request: Request) -> Response:
        serializer = TripRequestSerializer(data=request.data)
        if not serializer.is_valid():
            return error("invalid_request", serializer.errors, status.HTTP_400_BAD_REQUEST)
        data = serializer.validated_data
        trip = TripRequest(
            start=data["start"], finish=data["finish"], corridor_miles=data["corridor_miles"]
        )
        try:
            result = plan_trip(trip)
        except PlaceNotFound as exc:
            return error("place_not_found", str(exc), status.HTTP_404_NOT_FOUND)
        except (OutsideUSA, SamePlace, NoRouteFound, NoFuelInRange) as exc:
            code = {
                OutsideUSA: "outside_usa",
                SamePlace: "same_place",
                NoRouteFound: "no_route",
                NoFuelInRange: "no_fuel_in_range",
            }[type(exc)]
            return error(code, str(exc), status.HTTP_422_UNPROCESSABLE_ENTITY)
        except RoutingError as exc:
            logger.warning("Routing failed: %s", exc)
            return error("routing_unavailable", str(exc), status.HTTP_502_BAD_GATEWAY)

        plan = TripPlan.objects.create(start=trip.start, finish=trip.finish, result=result)
        return Response(with_links(request, plan), status=status.HTTP_201_CREATED)


class TripPlanDetailView(APIView):
    @extend_schema(responses={200: TripPlanSerializer}, summary="Get a saved trip plan")
    def get(self, request: Request, plan_id) -> Response:
        plan = get_object_or_404(TripPlan, pk=plan_id)
        return Response(with_links(request, plan))


def trip_plan_map(request, plan_id):
    """An HTML page drawing the route and fuel stops of a saved plan (Leaflet + OSM)."""
    plan = get_object_or_404(TripPlan, pk=plan_id)
    return render(request, "planner/map.html", {"plan": plan, "result": plan.result})
