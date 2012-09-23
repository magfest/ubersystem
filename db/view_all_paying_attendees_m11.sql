DROP VIEW IF EXISTS `view_allpayingattendees_m11`;
CREATE OR REPLACE ALGORITHM=UNDEFINED DEFINER=`root`@`localhost` SQL SECURITY DEFINER VIEW `view_allpayingattendees_m11` AS

select a.*
from (`m11`.`attendee` `a` join `m11`.`group` `g`)
where ((`a`.`paid` = 4) and (`a`.`group_id` = `g`.`id`) and
(`g`.`tables` = 0) and
(`g`.`amount_paid` > 0) and
(`g`.`amount_paid` >= `g`.`amount_owed`))
union all
select a.*
from `m11`.`attendee` `a`
where (`a`.`paid` = 1);