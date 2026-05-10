ALTER TABLE showroom_selling_details
DROP CONSTRAINT IF EXISTS showroom_selling_details_status_check;

UPDATE showroom_selling_details
SET selling_status = 'pending'
WHERE selling_status = 'reserved';

ALTER TABLE showroom_selling_details
ADD CONSTRAINT showroom_selling_details_status_check
CHECK (selling_status IN ('available', 'pending', 'sold'));
