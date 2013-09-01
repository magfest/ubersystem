-- new stored proc

-- CREATE TYPE daterecord as (day_offset int, date_of_offset TIMESTAMP);

CREATE LANGUAGE plpgsql;
CREATE OR REPLACE FUNCTION generate_reverse_date_sequence(last_day_of_sequence TIMESTAMP) RETURNS SETOF daterecord AS $body$
BEGIN


RETURN QUERY
SELECT 
day_offset,
last_day_of_sequence - (365 - day_offset) * INTERVAL '1 day' as date_of_offset
FROM generate_series(0,365) as day_offset 
ORDER BY day_offset DESC;



END
$body$ LANGUAGE plpgsql;