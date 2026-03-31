-- Gauge seed data (generated from pipeline/config/rivers.py)
-- Run after init_schema.sql has created the gauges table.

INSERT INTO gauges (usgs_gauge_id, name, river, lat, lon, flow_thresholds)
VALUES
  ('09035800', 'Spinney Reservoir', 'South Platte', 38.9097, -105.5666, '{"blowout": 500, "optimal_low": 80, "optimal_high": 250}'),
  ('09036000', 'Eleven Mile Canyon', 'South Platte', 38.9419, -105.4958, '{"blowout": 600, "optimal_low": 100, "optimal_high": 350}'),
  ('09033300', 'Deckers', 'South Platte', 39.2525, -105.2192, '{"blowout": 800, "optimal_low": 150, "optimal_high": 400}'),
  ('09034500', 'Cheesman Canyon', 'South Platte', 39.1886, -105.2511, '{"blowout": 700, "optimal_low": 100, "optimal_high": 350}'),
  ('07091200', 'Salida', 'Arkansas River', 38.5347, -106.0008, '{"blowout": 2000, "optimal_low": 200, "optimal_high": 700}'),
  ('07096000', 'Cañon City', 'Arkansas River', 38.4406, -105.2372, '{"blowout": 3000, "optimal_low": 300, "optimal_high": 1000}'),
  ('09081600', 'Ruedi to Basalt', 'Fryingpan River', 39.3672, -106.9281, '{"blowout": 400, "optimal_low": 60, "optimal_high": 200}'),
  ('09085000', 'Glenwood Springs', 'Roaring Fork River', 39.5486, -107.3247, '{"blowout": 3000, "optimal_low": 200, "optimal_high": 800}'),
  ('09057500', 'Silverthorne', 'Blue River', 39.6328, -106.0694, '{"blowout": 500, "optimal_low": 50, "optimal_high": 200}'),
  ('06752000', 'Canyon Mouth', 'Cache la Poudre', 40.6883, -105.1561, '{"blowout": 2000, "optimal_low": 150, "optimal_high": 600}'),
  ('09070000', 'Glenwood Springs', 'Colorado River', 39.5500, -107.3242, '{"blowout": 8000, "optimal_low": 500, "optimal_high": 2500}')
ON CONFLICT (usgs_gauge_id) DO UPDATE
  SET name = EXCLUDED.name,
      river = EXCLUDED.river,
      lat = EXCLUDED.lat,
      lon = EXCLUDED.lon,
      flow_thresholds = EXCLUDED.flow_thresholds;
