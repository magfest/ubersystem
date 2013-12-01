f () {
    errcode=$? # save the exit code as the first thing done in the trap function
    echo "error $errorcode"
    echo "the command executing at the time of the error was"
    echo "$BASH_COMMAND"
    echo "on line ${BASH_LINENO[0]}"
    # do some error handling, cleanup, logging, notification
    # $BASH_COMMAND contains the command that was being executed at the time of the trap
    # ${BASH_LINENO[0]} contains the line number in the script of that command
    # exit the script or return to try again, etc.
    exit $errcode  # or use some other value or do return instead
}
trap f ERR

rm -rfv env
python3.3 -m venv env
source ./env/bin/activate
python distribute_setup.py
cp ./env/local/bin/easy_install ./env/bin

mkdir -p ./env/local/bin
touch ./env/local/bin/placeholder
cp ./env/local/bin/* ./env/bin/

for pydep in Django psycopg2 py3k-bcrypt logging_unterpolation requests nose readline stripe CherryPy
do
    ./env/bin/easy_install $pydep
done
