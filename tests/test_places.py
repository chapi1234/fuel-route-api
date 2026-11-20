import httpx
import pytest
import respx

from geo.places import OutsideUSA, PlaceNotFound, geocode, resolve_offline

NOMINATIM = "https://nominatim.openstreetmap.org/search"


@pytest.mark.parametrize(
    ("query", "label", "lat", "lon"),
    [
        ("Denver, CO", "Denver, CO", 39.76, -104.88),
        ("denver, colorado", "Denver, CO", 39.76, -104.88),
        ("St. Louis, MO", "St. Louis, MO", 38.64, -90.24),
        ("Springfield, IL", "Springfield, IL", 39.79, -89.64),
        ("New York, NY, USA", "New York, NY", 40.66, -73.94),
    ],
)
def test_city_state_resolves_offline(query, label, lat, lon):
    place = resolve_offline(query)
    assert place.source == "places"
    assert place.label == label
    assert place.lat == pytest.approx(lat, abs=0.1)
    assert place.lon == pytest.approx(lon, abs=0.1)


def test_coordinates_are_used_as_given():
    place = resolve_offline(" 39.7392 , -104.9903 ")
    assert (place.lat, place.lon, place.source) == (39.7392, -104.9903, "coordinates")


def test_coordinates_outside_the_usa_are_rejected():
    with pytest.raises(OutsideUSA):
        resolve_offline("51.5072,-0.1276")  # London


@pytest.mark.parametrize("query", ["1600 Pennsylvania Ave NW Washington", "Nowhereville, ZZ"])
def test_other_inputs_need_the_geocoder(query):
    assert resolve_offline(query) is None


@respx.mock
def test_geocoder_fallback_returns_the_first_us_match():
    respx.get(NOMINATIM).respond(
        json=[{"lat": "38.8977", "lon": "-77.0365", "display_name": "The White House"}]
    )
    with httpx.Client() as client:
        place = geocode("1600 Pennsylvania Ave NW Washington", client)
    assert (place.lat, place.lon, place.source) == (38.8977, -77.0365, "geocoder")


@respx.mock
def test_geocoder_with_no_result_raises():
    respx.get(NOMINATIM).respond(json=[])
    with httpx.Client() as client, pytest.raises(PlaceNotFound):
        geocode("zzzz", client)
