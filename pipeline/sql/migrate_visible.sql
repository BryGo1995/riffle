BEGIN;

ALTER TABLE gauges ADD COLUMN IF NOT EXISTS visible BOOLEAN NOT NULL DEFAULT TRUE;

-- Malta gauge no longer returns flow data
UPDATE gauges SET visible = FALSE WHERE usgs_gauge_id = '07083710';

COMMIT;
