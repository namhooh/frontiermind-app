-- Populate missing meter location_description and metering_type for MOH01 (project_id=8)
UPDATE meter SET location_description = 'BBM1',        metering_type = 'Export only' WHERE id = 2;
UPDATE meter SET location_description = 'BBM2',        metering_type = 'Export only' WHERE id = 3;
UPDATE meter SET location_description = 'Bottles',     metering_type = 'Export only' WHERE id = 4;
UPDATE meter SET location_description = 'PPL 1',       metering_type = 'Export only' WHERE id = 5;
UPDATE meter SET location_description = 'PPL 2',       metering_type = 'Export only' WHERE id = 6;
