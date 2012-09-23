DELIMITER $$

DROP PROCEDURE IF EXISTS `get_cumulative_attendance_by_year` $$
CREATE DEFINER=`root`@`localhost` PROCEDURE `get_cumulative_attendance_by_year`(IN query_year INT)
BEGIN

DECLARE date_of_last_day_of_magfest DATE;
DECLARE current_magfest_year INT;

# get the last day of the magfest we're interested in
SELECT event_info.end_date INTO date_of_last_day_of_magfest FROM event_info WHERE event_info.magfest_number = query_year;

SELECT
all_days.day_offset as all_offset,
all_days.date as all_date,
IFNULL(amount_registered_that_day, 0) as amount_registered_that_day,
@attendance_so_far := @attendance_so_far + IFNULL(amount_registered_that_day, 0) as total_attendance_by_that_day
FROM
(SELECT @attendance_so_far:=0) as tmp5,
(
  # hackish subquery that looks complex but simply generates a sequence between 0 and 1000 which we then limit to 365
  # we'll use this in the JOIN below to make sure every day has a value, even if it's zero
  SELECT * FROM
  (
    SELECT
    365 - @day := @day + 1 as day_offset,
    DATE_SUB(date_of_last_day_of_magfest, INTERVAL @day DAY) as date
    FROM
    (select 0 union all select 1 union all select 3 union all select 4 union all select 5 union all select 6 union all select 6 union all select 7 union all select 8 union all select 9) t,
    (select 0 union all select 1 union all select 3 union all select 4 union all select 5 union all select 6 union all select 6 union all select 7 union all select 8 union all select 9) t2,
    (select 0 union all select 1 union all select 3 union all select 4 union all select 5 union all select 6 union all select 6 union all select 7 union all select 8 union all select 9) t3,
    (SELECT @day:=-1)as q
    LIMIT 366
  ) as tmp4
  ORDER BY date
)
as all_days
LEFT JOIN
(
    # the real meat of this query
    # generate the cumulative sum of the days where attendance changes exist
    # NOTE: this data will have gaps because some days don't have anyone registering
    SELECT
    date,
    365 - DATEDIFF(date_of_last_day_of_magfest, date) as day_offset,
    amount_registered_that_day
    FROM
    (
        SELECT
        date(registered) as date,
        COUNT(date(registered)) as amount_registered_that_day
        FROM
        (
            # combine data from both the current attendee table (current year, in progress data) and the attendee_archive (all previous years) table
            SELECT * FROM view_all_paying_attendees_all_magfests
        ) as temp1
        WHERE magfest_year = query_year
        GROUP BY date(registered)
        ORDER BY registered ASC
    ) as temp2
)  as days_with_data
ON all_days.day_offset = days_with_data.day_offset
ORDER BY all_days.date;

END $$

DELIMITER ;