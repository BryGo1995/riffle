import sys
sys.path.insert(0, "pipeline")
import pytest
import responses as rsps
from shared.usgs_client import fetch_gauge_reading, USGSReading

USGS_LATEST_URL = "https://api.waterdata.usgs.gov/ogcapi/v0/collections/latest-continuous/items"
USGS_RANGE_URL = "https://api.waterdata.usgs.gov/ogcapi/v0/collections/continuous/items"

MOCK_RESPONSE = {
    "type": "FeatureCollection",
    "features": [
        {
            "type": "Feature",
            "properties": {
                "monitoring_location_id": "USGS-09035800",
                "parameter_code": "00060",
                "time": "2026-03-30T20:00:00+00:00",
                "value": "245.0",
                "unit_of_measure": "ft^3/s",
            },
            "geometry": {"type": "Point", "coordinates": [-107.0, 39.0]},
        },
        {
            "type": "Feature",
            "properties": {
                "monitoring_location_id": "USGS-09035800",
                "parameter_code": "00010",
                "time": "2026-03-30T20:00:00+00:00",
                "value": "12.5",
                "unit_of_measure": "deg C",
            },
            "geometry": {"type": "Point", "coordinates": [-107.0, 39.0]},
        },
        {
            "type": "Feature",
            "properties": {
                "monitoring_location_id": "USGS-09035800",
                "parameter_code": "00065",
                "time": "2026-03-30T20:00:00+00:00",
                "value": "1.82",
                "unit_of_measure": "ft",
            },
            "geometry": {"type": "Point", "coordinates": [-107.0, 39.0]},
        },
    ],
    "numberReturned": 3,
}


@rsps.activate
def test_fetch_returns_usgs_reading():
    rsps.add(rsps.GET, USGS_LATEST_URL, json=MOCK_RESPONSE, status=200)
    result = fetch_gauge_reading("09035800")
    assert isinstance(result, USGSReading)
    assert result.flow_cfs == 245.0
    assert result.gauge_height_ft == 1.82


@rsps.activate
def test_water_temp_converted_from_celsius():
    rsps.add(rsps.GET, USGS_LATEST_URL, json=MOCK_RESPONSE, status=200)
    result = fetch_gauge_reading("09035800")
    # 12.5°C → 54.5°F
    assert abs(result.water_temp_f - 54.5) < 0.01


@rsps.activate
def test_missing_temp_returns_none():
    response_no_temp = {
        "type": "FeatureCollection",
        "features": [
            {
                "type": "Feature",
                "properties": {
                    "monitoring_location_id": "USGS-09035800",
                    "parameter_code": "00060",
                    "time": "2026-03-30T20:00:00+00:00",
                    "value": "100.0",
                    "unit_of_measure": "ft^3/s",
                },
                "geometry": {"type": "Point", "coordinates": [-107.0, 39.0]},
            },
            {
                "type": "Feature",
                "properties": {
                    "monitoring_location_id": "USGS-09035800",
                    "parameter_code": "00065",
                    "time": "2026-03-30T20:00:00+00:00",
                    "value": "1.0",
                    "unit_of_measure": "ft",
                },
                "geometry": {"type": "Point", "coordinates": [-107.0, 39.0]},
            },
        ],
        "numberReturned": 2,
    }
    rsps.add(rsps.GET, USGS_LATEST_URL, json=response_no_temp, status=200)
    result = fetch_gauge_reading("09035800")
    assert result.water_temp_f is None


@rsps.activate
def test_raises_on_http_error():
    rsps.add(rsps.GET, USGS_LATEST_URL, status=503)
    with pytest.raises(RuntimeError, match="USGS API"):
        fetch_gauge_reading("09035800")


from datetime import date
from shared.usgs_client import fetch_gauge_reading_range, USGSReadingTimestamped

MOCK_RANGE_RESPONSE = {
    "type": "FeatureCollection",
    "features": [
        {
            "type": "Feature",
            "properties": {
                "monitoring_location_id": "USGS-09035800",
                "parameter_code": "00060",
                "time": "2024-03-31T21:00:00+00:00",
                "value": "245.0",
                "unit_of_measure": "ft^3/s",
            },
            "geometry": {"type": "Point", "coordinates": [-107.0, 39.0]},
        },
        {
            "type": "Feature",
            "properties": {
                "monitoring_location_id": "USGS-09035800",
                "parameter_code": "00060",
                "time": "2024-03-31T22:00:00+00:00",
                "value": "248.0",
                "unit_of_measure": "ft^3/s",
            },
            "geometry": {"type": "Point", "coordinates": [-107.0, 39.0]},
        },
        {
            "type": "Feature",
            "properties": {
                "monitoring_location_id": "USGS-09035800",
                "parameter_code": "00010",
                "time": "2024-03-31T21:00:00+00:00",
                "value": "12.5",
                "unit_of_measure": "deg C",
            },
            "geometry": {"type": "Point", "coordinates": [-107.0, 39.0]},
        },
        {
            "type": "Feature",
            "properties": {
                "monitoring_location_id": "USGS-09035800",
                "parameter_code": "00010",
                "time": "2024-03-31T22:00:00+00:00",
                "value": "12.6",
                "unit_of_measure": "deg C",
            },
            "geometry": {"type": "Point", "coordinates": [-107.0, 39.0]},
        },
        {
            "type": "Feature",
            "properties": {
                "monitoring_location_id": "USGS-09035800",
                "parameter_code": "00065",
                "time": "2024-03-31T21:00:00+00:00",
                "value": "1.82",
                "unit_of_measure": "ft",
            },
            "geometry": {"type": "Point", "coordinates": [-107.0, 39.0]},
        },
        {
            "type": "Feature",
            "properties": {
                "monitoring_location_id": "USGS-09035800",
                "parameter_code": "00065",
                "time": "2024-03-31T22:00:00+00:00",
                "value": "1.85",
                "unit_of_measure": "ft",
            },
            "geometry": {"type": "Point", "coordinates": [-107.0, 39.0]},
        },
    ],
    "numberReturned": 6,
}


@rsps.activate
def test_fetch_gauge_reading_range_returns_timestamped_readings():
    rsps.add(rsps.GET, USGS_RANGE_URL, json=MOCK_RANGE_RESPONSE, status=200)
    results = fetch_gauge_reading_range(
        "09035800",
        start_date=date(2024, 3, 31),
        end_date=date(2024, 3, 31),
    )
    assert len(results) == 2
    assert all(isinstance(r, USGSReadingTimestamped) for r in results)


@rsps.activate
def test_fetch_gauge_reading_range_converts_temp_to_fahrenheit():
    rsps.add(rsps.GET, USGS_RANGE_URL, json=MOCK_RANGE_RESPONSE, status=200)
    results = fetch_gauge_reading_range(
        "09035800",
        start_date=date(2024, 3, 31),
        end_date=date(2024, 3, 31),
    )
    # 12.5°C → 54.5°F
    assert results[0].water_temp_f == pytest.approx(54.5)


@rsps.activate
def test_fetch_gauge_reading_range_sorted_by_time():
    rsps.add(rsps.GET, USGS_RANGE_URL, json=MOCK_RANGE_RESPONSE, status=200)
    results = fetch_gauge_reading_range(
        "09035800",
        start_date=date(2024, 3, 31),
        end_date=date(2024, 3, 31),
    )
    assert results[0].fetched_at < results[1].fetched_at


@rsps.activate
def test_fetch_gauge_reading_range_fetched_at_is_timezone_aware():
    rsps.add(rsps.GET, USGS_RANGE_URL, json=MOCK_RANGE_RESPONSE, status=200)
    results = fetch_gauge_reading_range(
        "09035800",
        start_date=date(2024, 3, 31),
        end_date=date(2024, 3, 31),
    )
    assert results[0].fetched_at.tzinfo is not None


# --- Daily collection tests ---

from shared.usgs_client import fetch_gauge_daily_range, USGSDailyReading

USGS_DAILY_URL = "https://api.waterdata.usgs.gov/ogcapi/v0/collections/daily/items"

MOCK_DAILY_RESPONSE = {
    "type": "FeatureCollection",
    "features": [
        # Day 1 — flow mean
        {
            "type": "Feature",
            "properties": {
                "monitoring_location_id": "USGS-09085000",
                "parameter_code": "00060",
                "statistic_id": "00003",
                "time": "2024-03-30",
                "value": "454",
                "unit_of_measure": "ft^3/s",
            },
        },
        # Day 1 — temp mean
        {
            "type": "Feature",
            "properties": {
                "monitoring_location_id": "USGS-09085000",
                "parameter_code": "00010",
                "statistic_id": "00003",
                "time": "2024-03-30",
                "value": "12.5",
                "unit_of_measure": "deg C",
            },
        },
        # Day 1 — temp max (should be filtered out)
        {
            "type": "Feature",
            "properties": {
                "monitoring_location_id": "USGS-09085000",
                "parameter_code": "00010",
                "statistic_id": "00001",
                "time": "2024-03-30",
                "value": "16.0",
                "unit_of_measure": "deg C",
            },
        },
        # Day 2 — flow mean
        {
            "type": "Feature",
            "properties": {
                "monitoring_location_id": "USGS-09085000",
                "parameter_code": "00060",
                "statistic_id": "00003",
                "time": "2024-03-31",
                "value": "461",
                "unit_of_measure": "ft^3/s",
            },
        },
    ],
    "numberReturned": 4,
}


@rsps.activate
def test_fetch_gauge_daily_range_returns_one_row_per_date():
    rsps.add(rsps.GET, USGS_DAILY_URL, json=MOCK_DAILY_RESPONSE, status=200)
    results = fetch_gauge_daily_range(
        "09085000",
        start_date=date(2024, 3, 30),
        end_date=date(2024, 3, 31),
    )
    assert len(results) == 2
    assert all(isinstance(r, USGSDailyReading) for r in results)


@rsps.activate
def test_fetch_gauge_daily_range_filters_to_mean_statistic():
    rsps.add(rsps.GET, USGS_DAILY_URL, json=MOCK_DAILY_RESPONSE, status=200)
    results = fetch_gauge_daily_range(
        "09085000",
        start_date=date(2024, 3, 30),
        end_date=date(2024, 3, 31),
    )
    day1 = next(r for r in results if r.observed_date == date(2024, 3, 30))
    # Should only see the mean (12.5°C → 54.5°F), not the max
    assert day1.water_temp_f == pytest.approx(54.5)


@rsps.activate
def test_fetch_gauge_daily_range_returns_sorted_by_date():
    rsps.add(rsps.GET, USGS_DAILY_URL, json=MOCK_DAILY_RESPONSE, status=200)
    results = fetch_gauge_daily_range(
        "09085000",
        start_date=date(2024, 3, 30),
        end_date=date(2024, 3, 31),
    )
    assert results[0].observed_date < results[1].observed_date


@rsps.activate
def test_fetch_gauge_daily_range_handles_missing_temp():
    response = {
        "type": "FeatureCollection",
        "features": [
            {
                "type": "Feature",
                "properties": {
                    "monitoring_location_id": "USGS-09085000",
                    "parameter_code": "00060",
                    "statistic_id": "00003",
                    "time": "2024-03-30",
                    "value": "100",
                    "unit_of_measure": "ft^3/s",
                },
            },
        ],
        "numberReturned": 1,
    }
    rsps.add(rsps.GET, USGS_DAILY_URL, json=response, status=200)
    results = fetch_gauge_daily_range(
        "09085000",
        start_date=date(2024, 3, 30),
        end_date=date(2024, 3, 30),
    )
    assert len(results) == 1
    assert results[0].water_temp_f is None
    assert results[0].flow_cfs == 100.0
