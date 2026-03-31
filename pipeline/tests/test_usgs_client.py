import sys
sys.path.insert(0, "pipeline")
import pytest
import responses as rsps
from shared.usgs_client import fetch_gauge_reading, USGSReading

USGS_BASE = "https://waterservices.usgs.gov/nwis/iv/"

MOCK_RESPONSE = {
    "value": {
        "timeSeries": [
            {
                "variable": {"variableCode": [{"value": "00060"}]},
                "values": [{"value": [{"value": "245.0", "dateTime": "2026-03-30T14:00:00.000-06:00"}]}],
            },
            {
                "variable": {"variableCode": [{"value": "00010"}]},
                "values": [{"value": [{"value": "12.5", "dateTime": "2026-03-30T14:00:00.000-06:00"}]}],
            },
            {
                "variable": {"variableCode": [{"value": "00065"}]},
                "values": [{"value": [{"value": "1.82", "dateTime": "2026-03-30T14:00:00.000-06:00"}]}],
            },
        ]
    }
}

@rsps.activate
def test_fetch_returns_usgs_reading():
    rsps.add(rsps.GET, USGS_BASE, json=MOCK_RESPONSE, status=200)
    result = fetch_gauge_reading("09035800")
    assert isinstance(result, USGSReading)
    assert result.flow_cfs == 245.0
    assert result.gauge_height_ft == 1.82

@rsps.activate
def test_water_temp_converted_from_celsius():
    rsps.add(rsps.GET, USGS_BASE, json=MOCK_RESPONSE, status=200)
    result = fetch_gauge_reading("09035800")
    # 12.5°C → 54.5°F
    assert abs(result.water_temp_f - 54.5) < 0.01

@rsps.activate
def test_missing_temp_returns_none():
    response_no_temp = {
        "value": {
            "timeSeries": [
                {
                    "variable": {"variableCode": [{"value": "00060"}]},
                    "values": [{"value": [{"value": "100.0", "dateTime": "2026-03-30T14:00:00.000-06:00"}]}],
                },
                {
                    "variable": {"variableCode": [{"value": "00065"}]},
                    "values": [{"value": [{"value": "1.0", "dateTime": "2026-03-30T14:00:00.000-06:00"}]}],
                },
            ]
        }
    }
    rsps.add(rsps.GET, USGS_BASE, json=response_no_temp, status=200)
    result = fetch_gauge_reading("09035800")
    assert result.water_temp_f is None

@rsps.activate
def test_raises_on_http_error():
    rsps.add(rsps.GET, USGS_BASE, status=503)
    with pytest.raises(RuntimeError, match="USGS API"):
        fetch_gauge_reading("09035800")


from datetime import date
from shared.usgs_client import fetch_gauge_reading_range, USGSReadingTimestamped

MOCK_RANGE_RESPONSE = {
    "value": {
        "timeSeries": [
            {
                "variable": {"variableCode": [{"value": "00060"}]},
                "values": [{"value": [
                    {"value": "245.0", "dateTime": "2024-03-31T14:00:00.000-07:00"},
                    {"value": "248.0", "dateTime": "2024-03-31T15:00:00.000-07:00"},
                ]}],
            },
            {
                "variable": {"variableCode": [{"value": "00010"}]},
                "values": [{"value": [
                    {"value": "12.5", "dateTime": "2024-03-31T14:00:00.000-07:00"},
                    {"value": "12.6", "dateTime": "2024-03-31T15:00:00.000-07:00"},
                ]}],
            },
            {
                "variable": {"variableCode": [{"value": "00065"}]},
                "values": [{"value": [
                    {"value": "1.82", "dateTime": "2024-03-31T14:00:00.000-07:00"},
                    {"value": "1.85", "dateTime": "2024-03-31T15:00:00.000-07:00"},
                ]}],
            },
        ]
    }
}


@rsps.activate
def test_fetch_gauge_reading_range_returns_timestamped_readings():
    rsps.add(rsps.GET, USGS_BASE, json=MOCK_RANGE_RESPONSE, status=200)
    results = fetch_gauge_reading_range(
        "09035800",
        start_date=date(2024, 3, 31),
        end_date=date(2024, 3, 31),
    )
    assert len(results) == 2
    assert all(isinstance(r, USGSReadingTimestamped) for r in results)


@rsps.activate
def test_fetch_gauge_reading_range_converts_temp_to_fahrenheit():
    rsps.add(rsps.GET, USGS_BASE, json=MOCK_RANGE_RESPONSE, status=200)
    results = fetch_gauge_reading_range(
        "09035800",
        start_date=date(2024, 3, 31),
        end_date=date(2024, 3, 31),
    )
    # 12.5°C → 54.5°F
    assert results[0].water_temp_f == pytest.approx(54.5)


@rsps.activate
def test_fetch_gauge_reading_range_sorted_by_time():
    rsps.add(rsps.GET, USGS_BASE, json=MOCK_RANGE_RESPONSE, status=200)
    results = fetch_gauge_reading_range(
        "09035800",
        start_date=date(2024, 3, 31),
        end_date=date(2024, 3, 31),
    )
    assert results[0].fetched_at < results[1].fetched_at


@rsps.activate
def test_fetch_gauge_reading_range_fetched_at_is_timezone_aware():
    rsps.add(rsps.GET, USGS_BASE, json=MOCK_RANGE_RESPONSE, status=200)
    results = fetch_gauge_reading_range(
        "09035800",
        start_date=date(2024, 3, 31),
        end_date=date(2024, 3, 31),
    )
    assert results[0].fetched_at.tzinfo is not None
