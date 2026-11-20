from decimal import Decimal

from stations.importer import read_stations

HEADER = "OPIS Truckstop ID,Truckstop Name,Address,City,State,Rack ID,Retail Price\n"


def write(tmp_path, prices: str, cities: str):
    prices_path = tmp_path / "prices.csv"
    cities_path = tmp_path / "cities.csv"
    prices_path.write_text(HEADER + prices, encoding="utf-8")
    cities_path.write_text("state,city_key,city,lat,lon,source\n" + cities, encoding="utf-8")
    return prices_path, cities_path


CITIES = "OK,bigcabin,Big Cabin,36.5,-95.2,census\nIL,effingham,Effingham,39.1,-88.5,census\n"


def test_keeps_the_lowest_price_for_a_repeated_station(tmp_path):
    prices, cities = write(
        tmp_path,
        '7,WOODSHED,"I-44, EXIT 283",Big Cabin,OK,307,3.10\n'
        '7,WOODSHED,"I-44, EXIT 283",Big Cabin,OK,307,2.95\n'
        '7,WOODSHED,"I-44, EXIT 283",Big Cabin,OK,307,3.05\n',
        CITIES,
    )
    stations, report = read_stations(prices, cities)
    assert len(stations) == 1
    assert stations[0]["price"] == Decimal("2.95")
    assert report.rows == 3


def test_skips_canadian_rows_and_trims_city_names(tmp_path):
    prices, cities = write(
        tmp_path,
        '1,A,US-1,Toronto,ON,1,1.50\n2,B,"I-57 & I-70, EXIT 159",Effingham      ,IL,2,3.40\n',
        CITIES,
    )
    stations, report = read_stations(prices, cities)
    assert [s["city"] for s in stations] == ["Effingham"]
    assert (stations[0]["latitude"], stations[0]["longitude"]) == (39.1, -88.5)
    assert report.skipped_non_us == 1


def test_counts_cities_without_coordinates(tmp_path):
    prices, cities = write(tmp_path, "3,C,US-2,Nowhere,TX,3,3.00\n", CITIES)
    stations, report = read_stations(prices, cities)
    assert stations == []
    assert report.skipped_unlocated == 1


def test_bundled_data_locates_every_us_station(settings):
    from pathlib import Path

    data = Path(settings.DATA_DIR)
    stations, report = read_stations(data / "fuel-prices.csv", data / "station_cities.csv")
    assert report.skipped_unlocated == 0
    assert report.skipped_non_us == 620
    assert len(stations) == 6626
