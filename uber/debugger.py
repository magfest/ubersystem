import os


# when debugging, if you kill the server, occasionally there will be lockfiles leftover.
# we'll kill them here. DO NOT CALL THIS IN PRODUCTION
def debugger_helper_remove_any_lockfiles():
    path_of_this_python_script = os.path.dirname(os.path.realpath(__file__))
    session_path = path_of_this_python_script + "/../sessions/"
    for lockfile in os.listdir(session_path):
        if lockfile.endswith(".lock"):
            os.remove(session_path + lockfile)

def debugger_helpers_all_init():
    debugger_helper_remove_any_lockfiles()