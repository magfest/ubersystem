DROP FUNCTION get_cumulative_attendance_by_year(TIMESTAMP);
DROP TYPE attendance_record;
CREATE TYPE attendance_record as (all_offset int, all_date TIMESTAMP, amount_registered_that_day BIGINT, total_attendance_by_that_day INT);

CREATE LANGUAGE plpgsql;
CREATE OR REPLACE FUNCTION get_cumulative_attendance_by_year(last_day_of_magfest TIMESTAMP) RETURNS SETOF attendance_record AS $body$

-- DECLARE 
-- attendance_so_far int := 0;    -- NOTE: postgres doesn't let us do cumulative sums like mysql does. ignore this.
BEGIN


RETURN QUERY SELECT
all_days.day_offset as all_offset,
all_days.date as all_date,
COALESCE(amount_registered_that_day, 0) as amount_registered_that_day,
-- attendance_so_far := attendance_so_far + COALESCE(amount_registered_that_day, 0) as total_attendance_by_that_day   -- BORKED in pgsql
0 as total_attendance_by_that_day -- BORKED in pgsql
FROM
(
	SELECT date_of_offset as date, day_offset 
	FROM generate_reverse_date_sequence(last_day_of_magfest) 
	ORDER BY date
) as all_days
LEFT OUTER JOIN
(
	-- the real meat of this query
	-- generate the cumulative sum of the days where attendance changes exist
	-- NOTE: this data will have gaps because some days dont have anyone registering
	-- we will fill in these gaps in the join outside this query
	SELECT
	date,
	365 - cast(last_day_of_magfest::date - date::date as int) as day_offset,
	amount_registered_that_day
	FROM
	(
		SELECT
		date,
		COUNT(date) as amount_registered_that_day
		FROM
		(
			SELECT date_trunc('day', registered) as date
			FROM view_allpayingattendees_m12
		) as temp1
		GROUP BY date
		ORDER BY date ASC
	) as temp2
) as days_with_data
ON all_days.day_offset = days_with_data.day_offset
ORDER BY all_days.date;


END
$body$ LANGUAGE plpgsql;