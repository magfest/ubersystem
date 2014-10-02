from uber.common import *
import subprocess, shlex

# admin utilities.  should not be used during normal ubersystem operations except by developers / sysadmins

# quick n dirty. don't use for anything real.
def run_shell_cmd(command_line, working_dir=None):
    args = shlex.split(command_line)
    p = subprocess.Popen(args, stdout=subprocess.PIPE, stderr=subprocess.PIPE, cwd=working_dir)
    out, err = p.communicate()
    return out

def run_git_cmd(cmd):
    git = "/usr/bin/git"
    uber_base_dir = os.path.abspath(os.path.join(os.path.dirname( __file__ ), '..', '..'))
    return run_shell_cmd(git + " " + cmd, working_dir=uber_base_dir)

@all_renderable(PEOPLE)
class Root:
    def index(self):
        return {}

    # this is quick and dirty.
    # print out some info relevant to developers such as what the current version of ubersystem this is,
    # which branch it is, etc.
    def gitinfo(self):
        git_branch_name = run_git_cmd("rev-parse --abbrev-ref HEAD")
        git_current_sha = run_git_cmd("rev-parse --verify HEAD")
        last_commit_log = run_git_cmd("show --name-status")
        git_status = run_git_cmd("status")

        return {
            'git_branch_name': git_branch_name,
            'git_current_sha': git_current_sha,
            'last_commit_log': last_commit_log,
            'git_status': git_status
        }