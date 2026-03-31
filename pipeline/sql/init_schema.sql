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
    gauge_height_ft DOUBLE PRECISION
);

CREATE INDEX IF NOT EXISTS idx_gauge_readings_gauge_fetched
    ON gauge_readings(gauge_id, fetched_at DESC);

-- Weather + forecast (one row per gauge per date)
CREATE TABLE IF NOT EXISTS weather_readings (
    id SERIAL PRIMARY KEY,
    gauge_id INTEGER REFERENCES gauges(id) ON DELETE CASCADE,
    date DATE NOT NULL,
    precip_mm DOUBLE PRECISION,
    air_temp_f DOUBLE PRECISION,
    is_forecast BOOLEAN NOT NULL DEFAULT FALSE,
    UNIQUE(gauge_id, date)
);

-- ML predictions (one row per gauge per date; upsert on re-score)
CREATE TABLE IF NOT EXISTS predictions (
    id SERIAL PRIMARY KEY,
    gauge_id INTEGER REFERENCES gauges(id) ON DELETE CASCADE,
    date DATE NOT NULL,
    condition VARCHAR(20) NOT NULL,
    confidence DOUBLE PRECISION,
    is_forecast BOOLEAN NOT NULL DEFAULT FALSE,
    model_version VARCHAR(100),
    scored_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW(),
    UNIQUE(gauge_id, date)
);

CREATE INDEX IF NOT EXISTS idx_predictions_gauge_date
    ON predictions(gauge_id, date DESC);
