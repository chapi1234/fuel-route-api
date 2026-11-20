from rest_framework import serializers


class TripRequestSerializer(serializers.Serializer):
    start = serializers.CharField(
        max_length=200, help_text='"City, ST", "lat,lon" or a US address, e.g. "Denver, CO"'
    )
    finish = serializers.CharField(max_length=200, help_text='e.g. "Chicago, IL"')
    corridor_miles = serializers.FloatField(
        required=False,
        default=10.0,
        min_value=1.0,
        max_value=50.0,
        help_text="How far off the route a station may be, in miles.",
    )
    stop_cost = serializers.FloatField(
        required=False,
        default=5.0,
        min_value=0.0,
        max_value=100.0,
        help_text=(
            "Dollars each stop is worth avoiding. 0 gives the lowest possible fuel bill, "
            "even if it means stopping for a few gallons to save cents."
        ),
    )


class PlaceSerializer(serializers.Serializer):
    query = serializers.CharField()
    label = serializers.CharField()
    lat = serializers.FloatField()
    lon = serializers.FloatField()
    resolved_by = serializers.ChoiceField(choices=["coordinates", "places", "geocoder"])


class StationSerializer(serializers.Serializer):
    opis_id = serializers.IntegerField()
    name = serializers.CharField()
    address = serializers.CharField()
    city = serializers.CharField()
    state = serializers.CharField()


class LocationSerializer(serializers.Serializer):
    lat = serializers.FloatField()
    lon = serializers.FloatField()


class FuelStopSerializer(serializers.Serializer):
    stop = serializers.IntegerField()
    mile = serializers.FloatField(help_text="Miles from the start, along the route.")
    off_route_miles = serializers.FloatField()
    station = StationSerializer()
    location = LocationSerializer()
    price_per_gallon = serializers.FloatField()
    gallons = serializers.FloatField()
    cost = serializers.FloatField()
    fuel_on_arrival_gallons = serializers.FloatField()


class GeometrySerializer(serializers.Serializer):
    type = serializers.CharField()
    coordinates = serializers.ListField(child=serializers.ListField(child=serializers.FloatField()))


class RouteSerializer(serializers.Serializer):
    distance_miles = serializers.FloatField()
    duration_hours = serializers.FloatField()
    provider = serializers.CharField()
    profile = serializers.CharField()
    geometry = GeometrySerializer(help_text="GeoJSON LineString, [lon, lat] pairs.")


class VehicleSerializer(serializers.Serializer):
    max_range_miles = serializers.FloatField()
    mpg = serializers.FloatField()
    tank_gallons = serializers.FloatField()
    starts_with_full_tank = serializers.BooleanField()


class SummarySerializer(serializers.Serializer):
    total_fuel_cost = serializers.FloatField(help_text="USD spent at the fuel stops.")
    gallons_purchased = serializers.FloatField()
    number_of_stops = serializers.IntegerField()
    average_price_per_gallon = serializers.FloatField(allow_null=True)
    trip_gallons = serializers.FloatField(help_text="Fuel burned over the whole trip.")
    starting_tank_gallons_used = serializers.FloatField()
    stations_within_corridor = serializers.IntegerField()
    corridor_miles = serializers.FloatField()
    stop_cost = serializers.FloatField()


class TripPlanSerializer(serializers.Serializer):
    id = serializers.UUIDField()
    map_url = serializers.URLField()
    start = PlaceSerializer()
    finish = PlaceSerializer()
    route = RouteSerializer()
    vehicle = VehicleSerializer()
    fuel_stops = FuelStopSerializer(many=True)
    summary = SummarySerializer()
    meta = serializers.DictField()


class ErrorSerializer(serializers.Serializer):
    error = serializers.CharField()
    detail = serializers.JSONField()
