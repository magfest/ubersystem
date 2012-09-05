-- MySQL Administrator dump 1.4
--
-- ------------------------------------------------------
-- Server version	5.1.39-community


/*!40101 SET @OLD_CHARACTER_SET_CLIENT=@@CHARACTER_SET_CLIENT */;
/*!40101 SET @OLD_CHARACTER_SET_RESULTS=@@CHARACTER_SET_RESULTS */;
/*!40101 SET @OLD_COLLATION_CONNECTION=@@COLLATION_CONNECTION */;
/*!40101 SET NAMES utf8 */;

/*!40014 SET @OLD_UNIQUE_CHECKS=@@UNIQUE_CHECKS, UNIQUE_CHECKS=0 */;
/*!40014 SET @OLD_FOREIGN_KEY_CHECKS=@@FOREIGN_KEY_CHECKS, FOREIGN_KEY_CHECKS=0 */;
/*!40101 SET @OLD_SQL_MODE=@@SQL_MODE, SQL_MODE='NO_AUTO_VALUE_ON_ZERO' */;


--
-- Create schema m11
--

CREATE DATABASE IF NOT EXISTS m11;
USE m11;

--
-- Temporary table structure for view `view_all_paying_attendees_all_magfests`
--
DROP TABLE IF EXISTS `view_all_paying_attendees_all_magfests`;
DROP VIEW IF EXISTS `view_all_paying_attendees_all_magfests`;
CREATE TABLE `view_all_paying_attendees_all_magfests` (
  `magfest_year` bigint(20),
  `id` bigint(20),
  `admin_notes` longtext,
  `affiliate` varchar(50),
  `age_group` int(11),
  `amount_paid` int(11),
  `amount_refunded` int(11),
  `badge_num` int(11),
  `badge_type` int(11),
  `can_spam` bigint(20),
  `checked_in` datetime,
  `comments` varchar(255),
  `ec_phone` varchar(20),
  `email` varchar(50),
  `extra_swag` varchar(255),
  `first_name` varchar(25),
  `found_how` varchar(100),
  `group_id` int(11),
  `interests` varchar(50),
  `international` bigint(20),
  `last_name` varchar(25),
  `paid` int(11),
  `phone` varchar(20),
  `registered` date,
  `ribbon` bigint(20),
  `shirt` bigint(11),
  `zip_code` varchar(20)
);

--
-- Temporary table structure for view `view_allpayingattendees_m10`
--
DROP TABLE IF EXISTS `view_allpayingattendees_m10`;
DROP VIEW IF EXISTS `view_allpayingattendees_m10`;
CREATE TABLE `view_allpayingattendees_m10` (
  `id` int(11),
  `placeholder` tinyint(4),
  `first_name` varchar(25),
  `last_name` varchar(25),
  `international` tinyint(4),
  `zip_code` varchar(20),
  `ec_phone` varchar(20),
  `phone` varchar(20),
  `email` varchar(50),
  `age_group` int(11),
  `interests` varchar(50),
  `found_how` varchar(100),
  `comments` varchar(255),
  `admin_notes` longtext,
  `affiliate` varchar(50),
  `extra_swag` varchar(255),
  `can_spam` tinyint(4),
  `group_id` int(11),
  `badge_num` int(11),
  `badge_type` int(11),
  `shirt` int(11),
  `ribbon` int(11),
  `registered` datetime,
  `checked_in` datetime,
  `paid` int(11),
  `amount_paid` int(11),
  `amount_refunded` int(11),
  `badge_printed_name` varchar(30),
  `got_merch` tinyint(4)
);

--
-- Temporary table structure for view `view_allpayingattendees_m11`
--
DROP TABLE IF EXISTS `view_allpayingattendees_m11`;
DROP VIEW IF EXISTS `view_allpayingattendees_m11`;
CREATE TABLE `view_allpayingattendees_m11` (
  `id` int(11),
  `group_id` int(11),
  `placeholder` tinyint(4),
  `first_name` varchar(25),
  `last_name` varchar(25),
  `international` tinyint(4),
  `zip_code` varchar(20),
  `ec_phone` varchar(20),
  `phone` varchar(20),
  `email` varchar(50),
  `age_group` int(11),
  `interests` varchar(50),
  `found_how` varchar(100),
  `comments` varchar(255),
  `admin_notes` longtext,
  `badge_num` int(11),
  `badge_type` int(11),
  `ribbon` int(11),
  `affiliate` varchar(50),
  `can_spam` tinyint(4),
  `regdesk_info` varchar(255),
  `extra_merch` varchar(255),
  `got_merch` tinyint(4),
  `registered` datetime,
  `checked_in` datetime,
  `paid` int(11),
  `amount_paid` int(11),
  `amount_refunded` int(11),
  `badge_printed_name` varchar(30),
  `staffing` tinyint(4),
  `requested_depts` varchar(50),
  `assigned_depts` varchar(50),
  `trusted` tinyint(4),
  `nonshift_hours` int(11),
  `fire_safety_cert` varchar(50)
);

--
-- Temporary table structure for view `view_allpayingattendees_m6`
--
DROP TABLE IF EXISTS `view_allpayingattendees_m6`;
DROP VIEW IF EXISTS `view_allpayingattendees_m6`;
CREATE TABLE `view_allpayingattendees_m6` (
  `id` int(11),
  `firstname` varchar(25),
  `lastname` varchar(25),
  `zipcode` char(5),
  `phone` varchar(15),
  `email` varchar(50),
  `foundhow` varchar(100),
  `camefor` varchar(25),
  `comments` varchar(255),
  `shirt` int(11),
  `business_id` int(11),
  `badge_num` int(11),
  `badge_type` int(11),
  `registered` date,
  `checkedin` datetime,
  `referer` varchar(255),
  `adminnotes` text,
  `paid` int(11),
  `amountpaid` int(11),
  `address` varchar(255),
  `agegroup` int(11),
  `refunded` int(11)
);

--
-- Temporary table structure for view `view_allpayingattendees_m7`
--
DROP TABLE IF EXISTS `view_allpayingattendees_m7`;
DROP VIEW IF EXISTS `view_allpayingattendees_m7`;
CREATE TABLE `view_allpayingattendees_m7` (
  `id` int(11),
  `first_name` varchar(25),
  `last_name` varchar(25),
  `international` tinyint(4),
  `zip_code` varchar(20),
  `ec_phone` varchar(20),
  `phone` varchar(20),
  `email` varchar(50),
  `age_group` int(11),
  `interests` varchar(50),
  `found_how` varchar(100),
  `tournaments` varchar(50),
  `tourney_sugg` varchar(50),
  `comments` varchar(255),
  `admin_notes` longtext,
  `group_id` int(11),
  `badge_num` int(11),
  `badge_type` int(11),
  `shirt` int(11),
  `registered` date,
  `checked_in` datetime,
  `referer` varchar(255),
  `paid` int(11),
  `amount_paid` int(11),
  `amount_refunded` int(11),
  `tourney_signups` varchar(50)
);

--
-- Temporary table structure for view `view_allpayingattendees_m8`
--
DROP TABLE IF EXISTS `view_allpayingattendees_m8`;
DROP VIEW IF EXISTS `view_allpayingattendees_m8`;
CREATE TABLE `view_allpayingattendees_m8` (
  `id` int(11),
  `first_name` varchar(25),
  `last_name` varchar(25),
  `international` tinyint(4),
  `zip_code` varchar(20),
  `ec_phone` varchar(20),
  `phone` varchar(20),
  `email` varchar(50),
  `age_group` int(11),
  `interests` varchar(50),
  `found_how` varchar(100),
  `comments` varchar(255),
  `admin_notes` longtext,
  `group_id` int(11),
  `badge_num` int(11),
  `badge_type` int(11),
  `shirt` int(11),
  `registered` date,
  `checked_in` datetime,
  `referer` varchar(255),
  `paid` int(11),
  `amount_paid` int(11),
  `amount_refunded` int(11),
  `affiliate` varchar(50),
  `extra_swag` varchar(255)
);

--
-- Temporary table structure for view `view_allpayingattendees_m9`
--
DROP TABLE IF EXISTS `view_allpayingattendees_m9`;
DROP VIEW IF EXISTS `view_allpayingattendees_m9`;
CREATE TABLE `view_allpayingattendees_m9` (
  `id` int(11),
  `first_name` varchar(25),
  `last_name` varchar(25),
  `international` tinyint(4),
  `zip_code` varchar(20),
  `ec_phone` varchar(20),
  `phone` varchar(20),
  `email` varchar(50),
  `age_group` int(11),
  `interests` varchar(50),
  `found_how` varchar(100),
  `comments` varchar(255),
  `admin_notes` longtext,
  `affiliate` varchar(50),
  `extra_swag` varchar(255),
  `can_spam` tinyint(4),
  `group_id` int(11),
  `badge_num` int(11),
  `badge_type` int(11),
  `shirt` int(11),
  `registered` datetime,
  `checked_in` datetime,
  `paid` int(11),
  `amount_paid` int(11),
  `amount_refunded` int(11),
  `ribbon` int(11)
);

--
-- Definition of procedure `get_cumulative_attendance_by_year`
--

DROP PROCEDURE IF EXISTS `get_cumulative_attendance_by_year`;

DELIMITER $$

/*!50003 SET @TEMP_SQL_MODE=@@SQL_MODE, SQL_MODE='STRICT_TRANS_TABLES,NO_AUTO_CREATE_USER,NO_ENGINE_SUBSTITUTION' */ $$
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
/*!50003 SET SESSION SQL_MODE=@TEMP_SQL_MODE */  $$

DELIMITER ;

--
-- Definition of view `view_all_paying_attendees_all_magfests`
--

DROP TABLE IF EXISTS `view_all_paying_attendees_all_magfests`;
DROP VIEW IF EXISTS `view_all_paying_attendees_all_magfests`;
CREATE ALGORITHM=UNDEFINED DEFINER=`root`@`localhost` SQL SECURITY DEFINER VIEW `view_all_paying_attendees_all_magfests` AS 
select 
11 AS `magfest_year`,`v`.`id` AS `id`,`v`.`admin_notes` AS `admin_notes`,`v`.`affiliate` AS `affiliate`,`v`.`age_group` AS `age_group`,`v`.`amount_paid` AS `amount_paid`,`v`.`amount_refunded` AS `amount_refunded`,`v`.`badge_num` AS `badge_num`,`v`.`badge_type` AS `badge_type`,`v`.`can_spam` AS `can_spam`,`v`.`checked_in` AS `checked_in`,`v`.`comments` AS `comments`,`v`.`ec_phone` AS `ec_phone`,`v`.`email` AS `email`,`v`.`extra_merch` AS `extra_swag`,`v`.`first_name` AS `first_name`,`v`.`found_how` AS `found_how`,`v`.`group_id` AS `group_id`,`v`.`interests` AS `interests`,`v`.`international` AS `international`,`v`.`last_name` AS `last_name`,`v`.`paid` AS `paid`,`v`.`phone` AS `phone`,`v`.`registered` AS `registered`,`v`.`ribbon` AS `ribbon`,0 AS `shirt`,`v`.`zip_code` AS `zip_code` 
from `view_allpayingattendees_m11` `v` 
union all 
select 
10 AS `magfest_year`,(`v`.`id` + 1000000) AS `id`,`v`.`admin_notes` AS `admin_notes`,`v`.`affiliate` AS `affiliate`,`v`.`age_group` AS `age_group`,`v`.`amount_paid` AS `amount_paid`,`v`.`amount_refunded` AS `amount_refunded`,`v`.`badge_num` AS `badge_num`,`v`.`badge_type` AS `badge_type`,`v`.`can_spam` AS `can_spam`,`v`.`checked_in` AS `checked_in`,`v`.`comments` AS `comments`,`v`.`ec_phone` AS `ec_phone`,`v`.`email` AS `email`,`v`.`extra_swag` AS `extra_swag`,`v`.`first_name` AS `first_name`,`v`.`found_how` AS `found_how`,`v`.`group_id` AS `group_id`,`v`.`interests` AS `interests`,`v`.`international` AS `international`,`v`.`last_name` AS `last_name`,`v`.`paid` AS `paid`,`v`.`phone` AS `phone`,`v`.`registered` AS `registered`,`v`.`ribbon` AS `ribbon`,`v`.`shirt` AS `shirt`,`v`.`zip_code` AS `zip_code` 
from `view_allpayingattendees_m10` `v` 
union all 
select 
9 AS `magfest_year`,(`v`.`id` + 900000) AS `id`,`v`.`admin_notes` AS `admin_notes`,`v`.`affiliate` AS `affiliate`,`v`.`age_group` AS `age_group`,`v`.`amount_paid` AS `amount_paid`,`v`.`amount_refunded` AS `amount_refunded`,`v`.`badge_num` AS `badge_num`,`v`.`badge_type` AS `badge_type`,`v`.`can_spam` AS `can_spam`,`v`.`checked_in` AS `checked_in`,`v`.`comments` AS `comments`,`v`.`ec_phone` AS `ec_phone`,`v`.`email` AS `email`,`v`.`extra_swag` AS `extra_swag`,`v`.`first_name` AS `first_name`,`v`.`found_how` AS `found_how`,`v`.`group_id` AS `group_id`,`v`.`interests` AS `interests`,`v`.`international` AS `international`,`v`.`last_name` AS `last_name`,`v`.`paid` AS `paid`,`v`.`phone` AS `phone`,`v`.`registered` AS `registered`,`v`.`ribbon` AS `ribbon`,`v`.`shirt` AS `shirt`,`v`.`zip_code` AS `zip_code` 
from `view_allpayingattendees_m9` `v` 
union all 
select 
8 AS `magfest_year`,(`v`.`id` + 800000) AS `id`,`v`.`admin_notes` AS `admin_notes`,`v`.`affiliate` AS `affiliate`,`v`.`age_group` AS `age_group`,`v`.`amount_paid` AS `amount_paid`,`v`.`amount_refunded` AS `amount_refunded`,`v`.`badge_num` AS `badge_num`,`v`.`badge_type` AS `badge_type`,0 AS `can_spam`,`v`.`checked_in` AS `checked_in`,`v`.`comments` AS `comments`,`v`.`ec_phone` AS `ec_phone`,`v`.`email` AS `email`,`v`.`extra_swag` AS `extra_swag`,`v`.`first_name` AS `first_name`,`v`.`found_how` AS `found_how`,`v`.`group_id` AS `group_id`,`v`.`interests` AS `interests`,`v`.`international` AS `international`,`v`.`last_name` AS `last_name`,`v`.`paid` AS `paid`,`v`.`phone` AS `phone`,`v`.`registered` AS `registered`,0 AS `ribbon`,`v`.`shirt` AS `shirt`,`v`.`zip_code` AS `zip_code` 
from `view_allpayingattendees_m8` `v` 
union all 
select 
7 AS `magfest_year`,(`v`.`id` + 700000) AS `id`,`v`.`admin_notes` AS `admin_notes`,'' AS `affiliate`,`v`.`age_group` AS `age_group`,`v`.`amount_paid` AS `amount_paid`,`v`.`amount_refunded` AS `amount_refunded`,`v`.`badge_num` AS `badge_num`,`v`.`badge_type` AS `badge_type`,0 AS `can_spam`,`v`.`checked_in` AS `checked_in`,`v`.`comments` AS `comments`,`v`.`ec_phone` AS `ec_phone`,`v`.`email` AS `email`,'' AS `extra_swag`,`v`.`first_name` AS `first_name`,`v`.`found_how` AS `found_how`,`v`.`group_id` AS `group_id`,`v`.`interests` AS `interests`,`v`.`international` AS `international`,`v`.`last_name` AS `last_name`,`v`.`paid` AS `paid`,`v`.`phone` AS `phone`,`v`.`registered` AS `registered`,0 AS `ribbon`,`v`.`shirt` AS `shirt`,`v`.`zip_code` AS `zip_code` 
from `view_allpayingattendees_m7` `v` 
union all 
select 
6 AS `magfest_year`,(`v`.`id` + 600000) AS `id`,`v`.`adminnotes` AS `admin_notes`,'' AS `affiliate`,`v`.`agegroup` AS `age_group`,`v`.`amountpaid` AS `amount_paid`,`v`.`refunded` AS `amount_refunded`,`v`.`badge_num` AS `badge_num`,`v`.`badge_type` AS `badge_type`,0 AS `can_spam`,`v`.`checkedin` AS `checked_in`,`v`.`comments` AS `comments`,0 AS `ec_phone`,`v`.`email` AS `email`,'' AS `extra_swag`,`v`.`firstname` AS `first_name`,`v`.`foundhow` AS `found_how`,`v`.`business_id` AS `group_id`,`v`.`camefor` AS `interests`,0 AS `international`,`v`.`lastname` AS `last_name`,`v`.`paid` AS `paid`,`v`.`phone` AS `phone`,`v`.`registered` AS `registered`,0 AS `ribbon`,`v`.`shirt` AS `shirt`,`v`.`zipcode` AS `zip_code` 
from `view_allpayingattendees_m6` `v`;


--
-- Definition of view `view_allpayingattendees_m6`
--

DROP TABLE IF EXISTS `view_allpayingattendees_m6`;
DROP VIEW IF EXISTS `view_allpayingattendees_m6`;
CREATE ALGORITHM=UNDEFINED DEFINER=`root`@`localhost` SQL SECURITY DEFINER VIEW `view_allpayingattendees_m6` AS 
select `a`.`id` AS `id`,`a`.`firstname` AS `firstname`,`a`.`lastname` AS `lastname`,`a`.`zipcode` AS `zipcode`,`a`.`phone` AS `phone`,`a`.`email` AS `email`,`a`.`foundhow` AS `foundhow`,`a`.`camefor` AS `camefor`,`a`.`comments` AS `comments`,`a`.`shirt` AS `shirt`,`a`.`business_id` AS `business_id`,`a`.`badge_num` AS `badge_num`,`a`.`badge_type` AS `badge_type`,`a`.`registered` AS `registered`,`a`.`checkedin` AS `checkedin`,`a`.`referer` AS `referer`,`a`.`adminnotes` AS `adminnotes`,`a`.`paid` AS `paid`,`a`.`amountpaid` AS `amountpaid`,`a`.`address` AS `address`,`a`.`agegroup` AS `agegroup`,`a`.`refunded` AS `refunded` 
from `m6`.`attendee` `a` 
where (isnull(`a`.`business_id`) and (`a`.`paid` = 1));

--
-- Definition of view `view_allpayingattendees_m7`
--

DROP TABLE IF EXISTS `view_allpayingattendees_m7`;
DROP VIEW IF EXISTS `view_allpayingattendees_m7`;
CREATE ALGORITHM=UNDEFINED DEFINER=`root`@`localhost` SQL SECURITY DEFINER VIEW `view_allpayingattendees_m7` AS 
select `a`.`id` AS `id`,`a`.`first_name` AS `first_name`,`a`.`last_name` AS `last_name`,`a`.`international` AS `international`,`a`.`zip_code` AS `zip_code`,`a`.`ec_phone` AS `ec_phone`,`a`.`phone` AS `phone`,`a`.`email` AS `email`,`a`.`age_group` AS `age_group`,`a`.`interests` AS `interests`,`a`.`found_how` AS `found_how`,`a`.`tournaments` AS `tournaments`,`a`.`tourney_sugg` AS `tourney_sugg`,`a`.`comments` AS `comments`,`a`.`admin_notes` AS `admin_notes`,`a`.`group_id` AS `group_id`,`a`.`badge_num` AS `badge_num`,`a`.`badge_type` AS `badge_type`,`a`.`shirt` AS `shirt`,`a`.`registered` AS `registered`,`a`.`checked_in` AS `checked_in`,`a`.`referer` AS `referer`,`a`.`paid` AS `paid`,`a`.`amount_paid` AS `amount_paid`,`a`.`amount_refunded` AS `amount_refunded`,`a`.`tourney_signups` AS `tourney_signups` 
from (`m7`.`_attendee` `a` join `m7`.`_group` `g`) 
where ((`a`.`paid` = 4) and (`a`.`group_id` = `g`.`id`) and (`g`.`tables` = 0) and (`g`.`amount_paid` > 0)) 
union all 
select `a`.`id` AS `id`,`a`.`first_name` AS `first_name`,`a`.`last_name` AS `last_name`,`a`.`international` AS `international`,`a`.`zip_code` AS `zip_code`,`a`.`ec_phone` AS `ec_phone`,`a`.`phone` AS `phone`,`a`.`email` AS `email`,`a`.`age_group` AS `age_group`,`a`.`interests` AS `interests`,`a`.`found_how` AS `found_how`,`a`.`tournaments` AS `tournaments`,`a`.`tourney_sugg` AS `tourney_sugg`,`a`.`comments` AS `comments`,`a`.`admin_notes` AS `admin_notes`,`a`.`group_id` AS `group_id`,`a`.`badge_num` AS `badge_num`,`a`.`badge_type` AS `badge_type`,`a`.`shirt` AS `shirt`,`a`.`registered` AS `registered`,`a`.`checked_in` AS `checked_in`,`a`.`referer` AS `referer`,`a`.`paid` AS `paid`,`a`.`amount_paid` AS `amount_paid`,`a`.`amount_refunded` AS `amount_refunded`,`a`.`tourney_signups` AS `tourney_signups` 
from `m7`.`_attendee` `a` 
where (`a`.`paid` = 1);

--
-- Definition of view `view_allpayingattendees_m8`
--

DROP TABLE IF EXISTS `view_allpayingattendees_m8`;
DROP VIEW IF EXISTS `view_allpayingattendees_m8`;
CREATE ALGORITHM=UNDEFINED DEFINER=`root`@`localhost` SQL SECURITY DEFINER VIEW `view_allpayingattendees_m8` AS select `a`.`id` AS `id`,`a`.`first_name` AS `first_name`,`a`.`last_name` AS `last_name`,`a`.`international` AS `international`,`a`.`zip_code` AS `zip_code`,`a`.`ec_phone` AS `ec_phone`,`a`.`phone` AS `phone`,`a`.`email` AS `email`,`a`.`age_group` AS `age_group`,`a`.`interests` AS `interests`,`a`.`found_how` AS `found_how`,`a`.`comments` AS `comments`,`a`.`admin_notes` AS `admin_notes`,`a`.`group_id` AS `group_id`,`a`.`badge_num` AS `badge_num`,`a`.`badge_type` AS `badge_type`,`a`.`shirt` AS `shirt`,`a`.`registered` AS `registered`,`a`.`checked_in` AS `checked_in`,`a`.`referer` AS `referer`,`a`.`paid` AS `paid`,`a`.`amount_paid` AS `amount_paid`,`a`.`amount_refunded` AS `amount_refunded`,`a`.`affiliate` AS `affiliate`,`a`.`extra_swag` AS `extra_swag` 
from (`m8`.`_attendee` `a` join `m8`.`_group` `g`) 
where ((`a`.`paid` = 4) and (`a`.`group_id` = `g`.`id`) and (`g`.`tables` = 0) and (`g`.`amount_paid` > 0)) 
union all 
select `a`.`id` AS `id`,`a`.`first_name` AS `first_name`,`a`.`last_name` AS `last_name`,`a`.`international` AS `international`,`a`.`zip_code` AS `zip_code`,`a`.`ec_phone` AS `ec_phone`,`a`.`phone` AS `phone`,`a`.`email` AS `email`,`a`.`age_group` AS `age_group`,`a`.`interests` AS `interests`,`a`.`found_how` AS `found_how`,`a`.`comments` AS `comments`,`a`.`admin_notes` AS `admin_notes`,`a`.`group_id` AS `group_id`,`a`.`badge_num` AS `badge_num`,`a`.`badge_type` AS `badge_type`,`a`.`shirt` AS `shirt`,`a`.`registered` AS `registered`,`a`.`checked_in` AS `checked_in`,`a`.`referer` AS `referer`,`a`.`paid` AS `paid`,`a`.`amount_paid` AS `amount_paid`,`a`.`amount_refunded` AS `amount_refunded`,`a`.`affiliate` AS `affiliate`,`a`.`extra_swag` AS `extra_swag` 
from `m8`.`_attendee` `a` 
where (`a`.`paid` = 1);

--
-- Definition of view `view_allpayingattendees_m9`
--

DROP TABLE IF EXISTS `view_allpayingattendees_m9`;
DROP VIEW IF EXISTS `view_allpayingattendees_m9`;
CREATE ALGORITHM=UNDEFINED DEFINER=`root`@`localhost` SQL SECURITY DEFINER VIEW `view_allpayingattendees_m9` AS select `a`.`id` AS `id`,`a`.`first_name` AS `first_name`,`a`.`last_name` AS `last_name`,`a`.`international` AS `international`,`a`.`zip_code` AS `zip_code`,`a`.`ec_phone` AS `ec_phone`,`a`.`phone` AS `phone`,`a`.`email` AS `email`,`a`.`age_group` AS `age_group`,`a`.`interests` AS `interests`,`a`.`found_how` AS `found_how`,`a`.`comments` AS `comments`,`a`.`admin_notes` AS `admin_notes`,`a`.`affiliate` AS `affiliate`,`a`.`extra_swag` AS `extra_swag`,`a`.`can_spam` AS `can_spam`,`a`.`group_id` AS `group_id`,`a`.`badge_num` AS `badge_num`,`a`.`badge_type` AS `badge_type`,`a`.`shirt` AS `shirt`,`a`.`registered` AS `registered`,`a`.`checked_in` AS `checked_in`,`a`.`paid` AS `paid`,`a`.`amount_paid` AS `amount_paid`,`a`.`amount_refunded` AS `amount_refunded`,`a`.`ribbon` AS `ribbon` 
from (`m9`.`attendee` `a` join `m9`.`group` `g`) 
where ((`a`.`paid` = 4) and (`a`.`group_id` = `g`.`id`) and (`g`.`tables` = 0) and (`g`.`amount_paid` > 0) and (`g`.`amount_paid` >= `g`.`amount_owed`)) 
union all 
select `a`.`id` AS `id`,`a`.`first_name` AS `first_name`,`a`.`last_name` AS `last_name`,`a`.`international` AS `international`,`a`.`zip_code` AS `zip_code`,`a`.`ec_phone` AS `ec_phone`,`a`.`phone` AS `phone`,`a`.`email` AS `email`,`a`.`age_group` AS `age_group`,`a`.`interests` AS `interests`,`a`.`found_how` AS `found_how`,`a`.`comments` AS `comments`,`a`.`admin_notes` AS `admin_notes`,`a`.`affiliate` AS `affiliate`,`a`.`extra_swag` AS `extra_swag`,`a`.`can_spam` AS `can_spam`,`a`.`group_id` AS `group_id`,`a`.`badge_num` AS `badge_num`,`a`.`badge_type` AS `badge_type`,`a`.`shirt` AS `shirt`,`a`.`registered` AS `registered`,`a`.`checked_in` AS `checked_in`,`a`.`paid` AS `paid`,`a`.`amount_paid` AS `amount_paid`,`a`.`amount_refunded` AS `amount_refunded`,`a`.`ribbon` AS `ribbon` 
from `m9`.`attendee` `a` 
where (`a`.`paid` = 1);


--
-- Definition of view `view_allpayingattendees_m10`
--

DROP TABLE IF EXISTS `view_allpayingattendees_m10`;
DROP VIEW IF EXISTS `view_allpayingattendees_m10`;
CREATE ALGORITHM=UNDEFINED DEFINER=`root`@`localhost` SQL SECURITY DEFINER VIEW `view_allpayingattendees_m10` AS 
select `a`.`id` AS `id`,`a`.`placeholder` AS `placeholder`,`a`.`first_name` AS `first_name`,`a`.`last_name` AS `last_name`,`a`.`international` AS `international`,`a`.`zip_code` AS `zip_code`,`a`.`ec_phone` AS `ec_phone`,`a`.`phone` AS `phone`,`a`.`email` AS `email`,`a`.`age_group` AS `age_group`,`a`.`interests` AS `interests`,`a`.`found_how` AS `found_how`,`a`.`comments` AS `comments`,`a`.`admin_notes` AS `admin_notes`,`a`.`affiliate` AS `affiliate`,`a`.`extra_swag` AS `extra_swag`,`a`.`can_spam` AS `can_spam`,`a`.`group_id` AS `group_id`,`a`.`badge_num` AS `badge_num`,`a`.`badge_type` AS `badge_type`,`a`.`shirt` AS `shirt`,`a`.`ribbon` AS `ribbon`,`a`.`registered` AS `registered`,`a`.`checked_in` AS `checked_in`,`a`.`paid` AS `paid`,`a`.`amount_paid` AS `amount_paid`,`a`.`amount_refunded` AS `amount_refunded`,`a`.`badge_printed_name` AS `badge_printed_name`,`a`.`got_merch` AS `got_merch` 
from (`mx`.`Attendee` `a` join `mx`.`Group` `g`) 
where ((`a`.`paid` = 4) and (`a`.`group_id` = `g`.`id`) and (`g`.`tables` = 0) and (`g`.`amount_paid` > 0) and (`g`.`amount_paid` >= `g`.`amount_owed`)) 
union all 
select `a`.`id` AS `id`,`a`.`placeholder` AS `placeholder`,`a`.`first_name` AS `first_name`,`a`.`last_name` AS `last_name`,`a`.`international` AS `international`,`a`.`zip_code` AS `zip_code`,`a`.`ec_phone` AS `ec_phone`,`a`.`phone` AS `phone`,`a`.`email` AS `email`,`a`.`age_group` AS `age_group`,`a`.`interests` AS `interests`,`a`.`found_how` AS `found_how`,`a`.`comments` AS `comments`,`a`.`admin_notes` AS `admin_notes`,`a`.`affiliate` AS `affiliate`,`a`.`extra_swag` AS `extra_swag`,`a`.`can_spam` AS `can_spam`,`a`.`group_id` AS `group_id`,`a`.`badge_num` AS `badge_num`,`a`.`badge_type` AS `badge_type`,`a`.`shirt` AS `shirt`,`a`.`ribbon` AS `ribbon`,`a`.`registered` AS `registered`,`a`.`checked_in` AS `checked_in`,`a`.`paid` AS `paid`,`a`.`amount_paid` AS `amount_paid`,`a`.`amount_refunded` AS `amount_refunded`,`a`.`badge_printed_name` AS `badge_printed_name`,`a`.`got_merch` AS `got_merch` 
from `mx`.`Attendee` `a` 
where (`a`.`paid` = 1);


--
-- Definition of view `view_allpayingattendees_m11`
--

DROP TABLE IF EXISTS `view_allpayingattendees_m11`;
DROP VIEW IF EXISTS `view_allpayingattendees_m11`;
CREATE ALGORITHM=UNDEFINED DEFINER=`root`@`localhost` SQL SECURITY DEFINER VIEW `view_allpayingattendees_m11` AS 
select `a`.`id` AS `id`,`a`.`group_id` AS `group_id`,`a`.`placeholder` AS `placeholder`,`a`.`first_name` AS `first_name`,`a`.`last_name` AS `last_name`,`a`.`international` AS `international`,`a`.`zip_code` AS `zip_code`,`a`.`ec_phone` AS `ec_phone`,`a`.`phone` AS `phone`,`a`.`email` AS `email`,`a`.`age_group` AS `age_group`,`a`.`interests` AS `interests`,`a`.`found_how` AS `found_how`,`a`.`comments` AS `comments`,`a`.`admin_notes` AS `admin_notes`,`a`.`badge_num` AS `badge_num`,`a`.`badge_type` AS `badge_type`,`a`.`ribbon` AS `ribbon`,`a`.`affiliate` AS `affiliate`,`a`.`can_spam` AS `can_spam`,`a`.`regdesk_info` AS `regdesk_info`,`a`.`extra_merch` AS `extra_merch`,`a`.`got_merch` AS `got_merch`,`a`.`registered` AS `registered`,`a`.`checked_in` AS `checked_in`,`a`.`paid` AS `paid`,`a`.`amount_paid` AS `amount_paid`,`a`.`amount_refunded` AS `amount_refunded`,`a`.`badge_printed_name` AS `badge_printed_name`,`a`.`staffing` AS `staffing`,`a`.`requested_depts` AS `requested_depts`,`a`.`assigned_depts` AS `assigned_depts`,`a`.`trusted` AS `trusted`,`a`.`nonshift_hours` AS `nonshift_hours`,`a`.`fire_safety_cert` AS `fire_safety_cert` 
from (`Attendee` `a` join `Group` `g`) 
where ((`a`.`paid` = 4) and 
(`a`.`group_id` = `g`.`id`) and 
(`g`.`tables` = 0) and 
(`g`.`amount_paid` > 0) and 
(`g`.`amount_paid` >= `g`.`amount_owed`)) 
union all 
select `a`.`id` AS `id`,`a`.`group_id` AS `group_id`,`a`.`placeholder` AS `placeholder`,`a`.`first_name` AS `first_name`,`a`.`last_name` AS `last_name`,`a`.`international` AS `international`,`a`.`zip_code` AS `zip_code`,`a`.`ec_phone` AS `ec_phone`,`a`.`phone` AS `phone`,`a`.`email` AS `email`,`a`.`age_group` AS `age_group`,`a`.`interests` AS `interests`,`a`.`found_how` AS `found_how`,`a`.`comments` AS `comments`,`a`.`admin_notes` AS `admin_notes`,`a`.`badge_num` AS `badge_num`,`a`.`badge_type` AS `badge_type`,`a`.`ribbon` AS `ribbon`,`a`.`affiliate` AS `affiliate`,`a`.`can_spam` AS `can_spam`,`a`.`regdesk_info` AS `regdesk_info`,`a`.`extra_merch` AS `extra_merch`,`a`.`got_merch` AS `got_merch`,`a`.`registered` AS `registered`,`a`.`checked_in` AS `checked_in`,`a`.`paid` AS `paid`,`a`.`amount_paid` AS `amount_paid`,`a`.`amount_refunded` AS `amount_refunded`,`a`.`badge_printed_name` AS `badge_printed_name`,`a`.`staffing` AS `staffing`,`a`.`requested_depts` AS `requested_depts`,`a`.`assigned_depts` AS `assigned_depts`,`a`.`trusted` AS `trusted`,`a`.`nonshift_hours` AS `nonshift_hours`,`a`.`fire_safety_cert` AS `fire_safety_cert` 
from `Attendee` `a` 
where (`a`.`paid` = 1);



--
-- Definition of table `event_info`
--

DROP TABLE IF EXISTS `event_info`;
CREATE TABLE `event_info` (
  `magfest_number` int(10) unsigned NOT NULL AUTO_INCREMENT COMMENT 'which magfest number (i.e. magfest 9, magfest 10, etc)',
  `end_date` datetime NOT NULL COMMENT 'day on which this magfest starts',
  `start_date` datetime NOT NULL COMMENT 'day on which this magfest ends',
  `current_magfest` tinyint(1) NOT NULL COMMENT 'if this is the current magfest or not',
  PRIMARY KEY (`magfest_number`)
) ENGINE=InnoDB AUTO_INCREMENT=13 DEFAULT CHARSET=latin1 ROW_FORMAT=DYNAMIC;

--
-- Dumping data for table `event_info`
--

/*!40000 ALTER TABLE `event_info` DISABLE KEYS */;
INSERT INTO `event_info` (`magfest_number`,`end_date`,`start_date`,`current_magfest`) VALUES 
 (6,'2008-01-06 00:00:00','2008-01-03 00:00:00',0),
 (7,'2009-01-04 00:00:00','2008-01-01 00:00:00',0),
 (8,'2010-01-04 00:00:00','2009-01-01 00:00:00',0),
 (9,'2011-01-16 00:00:00','2011-01-13 00:00:00',0),
 (10,'2012-01-08 00:00:00','2012-01-05 00:00:00',0),
 (11,'2013-01-06 00:00:00','2013-01-03 00:00:00',1),
 (12,'2014-01-05 00:00:00','2014-01-02 00:00:00',0);
/*!40000 ALTER TABLE `event_info` ENABLE KEYS */;



/*!40101 SET SQL_MODE=@OLD_SQL_MODE */;
/*!40014 SET FOREIGN_KEY_CHECKS=@OLD_FOREIGN_KEY_CHECKS */;
/*!40014 SET UNIQUE_CHECKS=@OLD_UNIQUE_CHECKS */;
/*!40101 SET CHARACTER_SET_CLIENT=@OLD_CHARACTER_SET_CLIENT */;
/*!40101 SET CHARACTER_SET_RESULTS=@OLD_CHARACTER_SET_RESULTS */;
/*!40101 SET COLLATION_CONNECTION=@OLD_COLLATION_CONNECTION */;
/*!40101 SET CHARACTER_SET_CLIENT=@OLD_CHARACTER_SET_CLIENT */;
