-- Drop tables that need schema changes (cascades to FK dependents)
DROP TABLE IF EXISTS predictions;
DROP TABLE IF EXISTS weather_readings;

-- Hourly weather readings
CREATE TABLE weather_readings (
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

-- Hourly predictions
CREATE TABLE predictions (
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

CREATE INDEX idx_predictions_gauge_datetime
    ON predictions(gauge_id, target_datetime DESC);

-- Add uniqueness to gauge_readings for idempotent backfill
ALTER TABLE gauge_readings
    DROP CONSTRAINT IF EXISTS gauge_readings_gauge_id_fetched_at_key;
ALTER TABLE gauge_readings
    ADD CONSTRAINT gauge_readings_gauge_id_fetched_at_key UNIQUE (gauge_id, fetched_at);
