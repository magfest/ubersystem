some quick reference notes on how to manipulate postgres quickly.
```
# switch to the postgres user
sudo bash
su postgres


# backup a database named 'mydbname' into a file named 'backupfile.sql'
sudo bash
su postgres
pg_dump mydbname -f backupfile.sql

# restore a database named 'mydbname' from a file named 'backupfile.sql'
sudo bash
service postgresql restart        
su postgres
psql                              
    DROP DATABASE mydbname;
    CREATE DATABASE mydbname;
psql -d mydbname -f backupfile.sql

# select from an attende (this exact syntax is super-important)
SELECT * FROM "Attendee";

# create a database cluster if you blew it up
/usr/lib/postgresql/9.3/bin/initdb /var/lib/postgresql/9.3/main
or as root:
su - postgres -c "/usr/lib/postgresql/9.3/bin/initdb /var/lib/postgresql/9.3/main"
```
