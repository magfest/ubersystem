DROP VIEW IF EXISTS view_allpayingattendees_m12;
CREATE VIEW view_allpayingattendees_m12 AS

-- the 'paid' field is stored as a hash, here are the values:
-- PAID = 254570300
-- PAID_BY_GROUP = 149950189
-- DOESNT_NEED_TO = 231980499
-- TODO: it would be really awesome if postgres allowed constants, or we didn't store this as a hash.

-- 2 part query. 

-- NOTE: THIS QUERY DOES NOT CALCULATE AMOUNTS PAID CORRECTLY, DONT USE FOR THAT!!

SELECT
a.id, a.admin_notes, a.affiliate, a.age_group,
a.badge_num, a.badge_type, a.can_spam, a.checked_in, a.comments, a.ec_phone, a.email,
a.extra_merch, a.first_name, a.found_how, a.group_id, a.interests, a.international, a.last_name,
a.paid, a.phone, a.registered, a.ribbon, a.zip_code
FROM  "Attendee" AS a LEFT OUTER JOIN "Group" AS g ON a.group_id = g.id
WHERE 
(	
	-- first part gets attendees in groups that are not dealers (if a group has zero tables, it's not a dealer)
	-- this will not get non-group attendees (you can tell if in a group or not by the 'paid' attribute)
	g.id IS NOT NULL 					AND
	a.paid = 149950189 					AND
	g.tables = 0 						AND
	g.amount_paid > 0 					AND
	g.amount_paid >= g.amount_owed
)
OR
(	
	-- second part gets attendees not in groups that have paid
	a.paid = 254570300 
)