Some quick reference notes on common PostgreSQL tasks:
```
# switch to the postgres user
sudo bash
su postgres

# as postgres user, commandline drop and create database (IRRETRIEVABLY DESTROYS ALL DATA IN mydbname)
dropdb mydbname
createdb mydbname


# another way to drop the contents of a database without dropping the database itself
psql -U some_user -f drop_schema.sql mydbname

# where drop_schema.sql:
DROP SCHEMA public CASCADE;
CREATE SCHEMA IF NOT EXISTS public AUTHORIZATION some_user;
GRANT ALL ON SCHEMA public TO public;
GRANT ALL ON SCHEMA public TO some_user;


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

# grant all on a database to a user
GRANT ALL PRIVILEGES ON DATABASE some_database_name TO some_username;

# after restoring the DB, check the most recent registered attendee
SELECT registered FROM attendee ORDER BY registered desc LIMIT 1;

# select from an attende (this exact syntax and capitalization is super-important)
SELECT * FROM "Attendee";

# create a database cluster if you blew it up
/usr/lib/postgresql/9.3/bin/initdb /var/lib/postgresql/9.3/main
or as root:
su - postgres -c "/usr/lib/postgresql/9.3/bin/initdb /var/lib/postgresql/9.3/main"
```
