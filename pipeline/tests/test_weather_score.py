import sys
sys.path.insert(0, "pipeline")
from plugins.ml.weather_score import score_weather_only
from plugins.ml.train import CONDITION_CLASSES


# --- Return type ---

def test_returns_tuple():
    result = score_weather_only(
        air_temp_f=55.0, precip_mm=0.0, precip_probability=10,
        snowfall_mm=0.0, wind_speed_mph=5.0,
    )
    assert isinstance(result, tuple) and len(result) == 2


def test_confidence_is_float_between_0_and_1():
    _, conf = score_weather_only(
        air_temp_f=55.0, precip_mm=0.0, precip_probability=10,
        snowfall_mm=0.0, wind_speed_mph=5.0,
    )
    assert 0.0 < conf <= 1.0


def test_condition_is_valid_label():
    cond, _ = score_weather_only(
        air_temp_f=55.0, precip_mm=0.0, precip_probability=10,
        snowfall_mm=0.0, wind_speed_mph=5.0,
    )
    assert cond in CONDITION_CLASSES


# --- Rule boundaries ---

def test_blown_out_extreme_precip_mm():
    cond, _ = score_weather_only(
        air_temp_f=55.0, precip_mm=21.0, precip_probability=50,
        snowfall_mm=0.0, wind_speed_mph=5.0,
    )
    assert cond == "Blown Out"


def test_blown_out_high_probability_and_heavy_rain():
    cond, _ = score_weather_only(
        air_temp_f=55.0, precip_mm=12.0, precip_probability=85,
        snowfall_mm=0.0, wind_speed_mph=5.0,
    )
    assert cond == "Blown Out"


def test_poor_high_precip_probability():
    cond, _ = score_weather_only(
        air_temp_f=55.0, precip_mm=3.0, precip_probability=70,
        snowfall_mm=0.0, wind_speed_mph=5.0,
    )
    assert cond == "Poor"


def test_poor_freezing_temp():
    cond, _ = score_weather_only(
        air_temp_f=30.0, precip_mm=0.0, precip_probability=0,
        snowfall_mm=0.0, wind_speed_mph=5.0,
    )
    assert cond == "Poor"


def test_poor_significant_snowfall():
    cond, _ = score_weather_only(
        air_temp_f=32.0, precip_mm=0.0, precip_probability=20,
        snowfall_mm=5.0, wind_speed_mph=5.0,
    )
    assert cond == "Poor"


def test_fair_moderate_precip_probability():
    cond, _ = score_weather_only(
        air_temp_f=60.0, precip_mm=1.0, precip_probability=45,
        snowfall_mm=0.0, wind_speed_mph=5.0,
    )
    assert cond == "Fair"


def test_fair_marginal_cold_temp():
    cond, _ = score_weather_only(
        air_temp_f=40.0, precip_mm=0.0, precip_probability=10,
        snowfall_mm=0.0, wind_speed_mph=5.0,
    )
    assert cond == "Fair"


def test_excellent_ideal_conditions():
    cond, _ = score_weather_only(
        air_temp_f=58.0, precip_mm=0.0, precip_probability=10,
        snowfall_mm=0.0, wind_speed_mph=5.0,
    )
    assert cond == "Excellent"


def test_good_decent_conditions():
    cond, _ = score_weather_only(
        air_temp_f=72.0, precip_mm=1.0, precip_probability=20,
        snowfall_mm=0.0, wind_speed_mph=8.0,
    )
    assert cond == "Good"


# --- Confidence ceiling (weather-only is less certain than ML model) ---

def test_confidence_ceiling_across_conditions():
    cases = [
        dict(air_temp_f=55.0, precip_mm=25.0, precip_probability=90, snowfall_mm=0.0, wind_speed_mph=5.0),
        dict(air_temp_f=30.0, precip_mm=0.0, precip_probability=0, snowfall_mm=0.0, wind_speed_mph=5.0),
        dict(air_temp_f=58.0, precip_mm=0.0, precip_probability=5, snowfall_mm=0.0, wind_speed_mph=3.0),
        dict(air_temp_f=72.0, precip_mm=1.0, precip_probability=20, snowfall_mm=0.0, wind_speed_mph=8.0),
    ]
    for kwargs in cases:
        _, conf = score_weather_only(**kwargs)
        assert conf <= 0.75, f"confidence {conf} exceeds ceiling for {kwargs}"
