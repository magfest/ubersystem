-- new stored proc

SELECT 
day_offset,
TIMESTAMP '2014-01-06' - (365 - day_offset) * INTERVAL '1 day' as date
FROM generate_series(0,365) as day_offset 
ORDER BY day_offset DESC;