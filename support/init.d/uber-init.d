#!/bin/bash
# Dom wrote this. it sucks.

RETVAL=0;

start() {
echo "Starting All Magfest Ubersystems"
/bin/su uber -c "cd /home/uber/www/mx/ && ./run-as-daemon.sh"
}

stop() {
echo "Stopping All Magfest Ubersystems"
/bin/su uber -c "killall python2.7"
}

restart() {
stop
start
}

case "$1" in
start)
  start
;;
stop)
  stop
;;
restart)
  restart
;;
*)

echo $"Usage: $0 {start|stop|restart}"
exit 1
esac

exit $RETVAL
