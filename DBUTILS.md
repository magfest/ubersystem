some quick reference notes on how to manipulate postgres quickly.
```
# switch to the postgres user
sudo bash
su postgres


# backup a database named 'mydbname' into a file named 'uber-backup-2014-11-20-08:32:50.sql' (or whatever today's date is)
sudo bash
su postgres
pg_dump mydbname -f uber-backup-`date +%F-%H:%M:%S`.sql

# same thing as above but all one command, if you're already root
su postgres -c 'pg_dump mydbname -f /home/backups/uber-backup-`date +%F-%H:%M:%S`.sql'

# restore a database named 'mydbname' from a file named 'backupfile.sql'
sudo bash
service postgresql restart        
su postgres
psql                              
    DROP DATABASE mydbname;
    CREATE DATABASE mydbname;
psql -d mydbname -f backupfile.sql

# after restoring the DB, check the most recent registered attendee
SELECT registered FROM attendee ORDER BY registered desc LIMIT 1;

# select from an attende (this exact syntax and capitalization is super-important)
SELECT * FROM "Attendee";

# create a database cluster if you blew it up
/usr/lib/postgresql/9.3/bin/initdb /var/lib/postgresql/9.3/main
or as root:
su - postgres -c "/usr/lib/postgresql/9.3/bin/initdb /var/lib/postgresql/9.3/main"
```
