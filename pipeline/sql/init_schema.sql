-- Gauge registry
CREATE TABLE IF NOT EXISTS gauges (
    id SERIAL PRIMARY KEY,
    usgs_gauge_id VARCHAR(20) UNIQUE NOT NULL,
    name VARCHAR(100) NOT NULL,
    river VARCHAR(100) NOT NULL,
    lat DOUBLE PRECISION NOT NULL,
    lon DOUBLE PRECISION NOT NULL,
    flow_thresholds JSONB NOT NULL
);

-- Raw USGS readings (one row per gauge per fetch)
CREATE TABLE IF NOT EXISTS gauge_readings (
    id SERIAL PRIMARY KEY,
    gauge_id INTEGER REFERENCES gauges(id) ON DELETE CASCADE,
    fetched_at TIMESTAMP WITH TIME ZONE NOT NULL,
    flow_cfs DOUBLE PRECISION,
    water_temp_f DOUBLE PRECISION,
    gauge_height_ft DOUBLE PRECISION,
    UNIQUE(gauge_id, fetched_at)
);

CREATE INDEX IF NOT EXISTS idx_gauge_readings_gauge_fetched
    ON gauge_readings(gauge_id, fetched_at DESC);

-- Hourly weather readings
CREATE TABLE IF NOT EXISTS weather_readings (
    id                    SERIAL PRIMARY KEY,
    gauge_id              INTEGER REFERENCES gauges(id) ON DELETE CASCADE,
    observed_at           TIMESTAMP WITH TIME ZONE NOT NULL,
    precip_mm             DOUBLE PRECISION,
    precip_probability    INTEGER,
    air_temp_f            DOUBLE PRECISION,
    snowfall_mm           DOUBLE PRECISION,
    wind_speed_mph        DOUBLE PRECISION,
    weather_code          INTEGER,
    cloud_cover_pct       INTEGER,
    surface_pressure_hpa  DOUBLE PRECISION,
    is_forecast           BOOLEAN NOT NULL DEFAULT FALSE,
    UNIQUE(gauge_id, observed_at)
);

-- Hourly ML predictions
CREATE TABLE IF NOT EXISTS predictions (
    id              SERIAL PRIMARY KEY,
    gauge_id        INTEGER REFERENCES gauges(id) ON DELETE CASCADE,
    target_datetime TIMESTAMP WITH TIME ZONE NOT NULL,
    condition       VARCHAR(20) NOT NULL,
    confidence      DOUBLE PRECISION,
    is_forecast     BOOLEAN NOT NULL DEFAULT FALSE,
    model_version   VARCHAR(100),
    scored_at       TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW(),
    UNIQUE(gauge_id, target_datetime)
);

CREATE INDEX IF NOT EXISTS idx_predictions_gauge_datetime
    ON predictions(gauge_id, target_datetime DESC);

-- Daily aggregated USGS readings (one row per gauge per UTC date)
CREATE TABLE IF NOT EXISTS gauge_readings_daily (
    id            SERIAL PRIMARY KEY,
    gauge_id      INTEGER REFERENCES gauges(id) ON DELETE CASCADE,
    observed_date DATE NOT NULL,
    flow_cfs      DOUBLE PRECISION,
    water_temp_f  DOUBLE PRECISION,
    UNIQUE(gauge_id, observed_date)
);

CREATE INDEX IF NOT EXISTS idx_gauge_readings_daily_gauge_date
    ON gauge_readings_daily(gauge_id, observed_date DESC);

-- Daily aggregated weather (one row per gauge per local date).
-- Columns map to Open-Meteo daily archive variables; cloud_cover and
-- surface_pressure are intentionally omitted (no daily aggregate available)
-- and wind_speed is the daily max rather than mean for the same reason.
CREATE TABLE IF NOT EXISTS weather_readings_daily (
    id                    SERIAL PRIMARY KEY,
    gauge_id              INTEGER REFERENCES gauges(id) ON DELETE CASCADE,
    observed_date         DATE NOT NULL,
    precip_mm_sum         DOUBLE PRECISION,
    air_temp_f_mean       DOUBLE PRECISION,
    air_temp_f_min        DOUBLE PRECISION,
    air_temp_f_max        DOUBLE PRECISION,
    snowfall_mm_sum       DOUBLE PRECISION,
    wind_speed_mph_max    DOUBLE PRECISION,
    is_forecast           BOOLEAN NOT NULL DEFAULT FALSE,
    UNIQUE(gauge_id, observed_date)
);

CREATE INDEX IF NOT EXISTS idx_weather_readings_daily_gauge_date
    ON weather_readings_daily(gauge_id, observed_date DESC);

-- Daily ML predictions (current day + forecast days)
CREATE TABLE IF NOT EXISTS predictions_daily (
    id              SERIAL PRIMARY KEY,
    gauge_id        INTEGER REFERENCES gauges(id) ON DELETE CASCADE,
    target_date     DATE NOT NULL,
    condition       VARCHAR(20) NOT NULL,
    confidence      DOUBLE PRECISION,
    is_forecast     BOOLEAN NOT NULL DEFAULT FALSE,
    model_version   VARCHAR(100),
    scored_at       TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW(),
    UNIQUE(gauge_id, target_date)
);

CREATE INDEX IF NOT EXISTS idx_predictions_daily_gauge_date
    ON predictions_daily(gauge_id, target_date DESC);
