from uber.common import *
import shlex
import subprocess

# admin utilities.  should not be used during normal ubersystem operations except by developers / sysadmins


# quick n dirty. don't use for anything real.
def run_shell_cmd(command_line, working_dir=None):
    args = shlex.split(command_line)
    p = subprocess.Popen(args, stdout=subprocess.PIPE, stderr=subprocess.PIPE, cwd=working_dir)
    out, err = p.communicate()
    return out


def run_git_cmd(cmd):
    git = "/usr/bin/git"
    uber_base_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..'))
    return run_shell_cmd(git + " " + cmd, working_dir=uber_base_dir)


def generate_test_email_models():
    test_models = dict()

    attendee = Attendee(first_name='John', last_name='Dudebro', email='hey@hey.com')
    attendee2 = Attendee(first_name='Ima', last_name='Coolman', email='bro@bro.com')
    test_models[Attendee] = attendee

    group = Group(name="the coolest group", leader=attendee)
    test_models[Group] = group

    try:
        import panels
        event = panels.Event(name="Cool Event Bro", start_time=c.EPOCH,
                             duration=30, description="This is cool as anything")
        test_models[panels.PanelApplication] = panels.PanelApplication(event=event,
                                                                       name="My Panel Is Better Than Yours")
    except:
        pass

    try:
        import bands
        test_models[bands.Band] = bands.Band(
            group=Group(name="DE Coolest Bandz2", leader=attendee),
            info=bands.BandInfo(),
            bio=bands.BandBio(),
            taxes=bands.BandTaxes(),
            stage_plot=bands.BandStagePlot(),
            panel=bands.BandPanel(),
            merch=bands.BandMerch(),
            charity=bands.BandCharity()
        )
    except:
        pass

    try:
        import attendee_tournaments
        test_models[attendee_tournaments.AttendeeTournament] = attendee_tournaments.AttendeeTournament(
            game="Mario 6", first_name="Joe", last_name="Dudeman"
        )
    except:
        pass

    try:
        import hotel
        test_models[hotel.Room] = hotel.Room(
            assignments=[hotel.RoomAssignment(attendee=attendee), hotel.RoomAssignment(attendee=attendee2)],
            nights=','.join(map(str, c.CORE_NIGHTS))
        )
    except:
        pass

    try:
        import mivs

        game = mivs.IndieGame(
            title="Mario 7",
        )
        test_models[mivs.IndieGame] = game

        test_models[mivs.IndieStudio] = mivs.IndieStudio(
            group=group,
            name="Bossman Studios",
            games=[game],
            developers=[mivs.IndieDeveloper(
                first_name="Mancrunch",
                last_name="Jones",
                primary_contact=True
            )]
        )

        test_models[mivs.IndieJudge] = mivs.IndieJudge(
            admin_account=AdminAccount(attendee=attendee),
        )
    except:
        pass

    return test_models


@all_renderable(c.PEOPLE)
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

    def test_all_emails(self):
        test_models = generate_test_email_models()

        rendered_emails = []
        for email in [email[1] for email in AutomatedEmail.instances.items()]:
            if email.model not in test_models:
                rendered = "<font color='red'>Skipping {} because we don't have the model yet.</font>".format(email.subject)
            else:
                rendered = email.render(test_models[email.model]).decode('utf-8')
                if not email.is_html():
                    rendered = "<pre>{}</pre>".format(rendered)

            rendered_emails.append({'text': rendered, 'subject': email.subject})

        return {
            'emails': rendered_emails
        }
