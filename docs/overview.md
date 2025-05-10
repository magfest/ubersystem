# Ubersystem/RAMS Crash Course

Ubersystem (old name used by MAGFest, which also calls it Reggie) / RAMS (newer name used by MFF) is a 15+-year old registration system written primarily in Python. As a web app written before Django hit 1.0, it is best described as “idiosyncratic.” The WTForms overhaul is one of the biggest projects put forth in an effort to making contributing to the codebase feasible for people who are not me. I greatly appreciate your interest and hope you find this guide helpful.

Below are the highlights of what you need to know about Ubersystem before reading this guide.

## Code Structure

Ubersystem is split into two main components: the [main plugin](https://github.com/magfest/ubersystem/) and **event plugins**. These are separate repositories that are combined during runtime if they are present in co-existing folders. The former comprises the vast majority of the code, while the latter is a way to expand or override templates, models, and forms.

Generally, one event plugin is combined with the main plugin and corresponds with each event, e.g., Super MAGFest uses the [magprime](https://github.com/magfest/magprime) plugin to implement custom logic tailored to the event.

## Database Definitions

Database models are defined declaratively using [SQLAlchemy](https://www.sqlalchemy.org/). All model declarations can be found in `uber/models/`. Generally speaking, if you are adding fields or forms, you will need to add corresponding model declarations. Models deserve their own guide, but the basic types should be *relatively* straightforward.

We use [Alembic](https://alembic.sqlalchemy.org/en/latest/) to handle database migrations. There is an excellent and only slightly out of date [README](https://github.com/magfest/ubersystem/blob/main/alembic/README.md) for how to run alembic migrations in Ubersystem, so please check it out.

## Page Handlers and Templates

[CherryPy](https://docs.cherrypy.dev/en/latest/) handles our routing. Page handlers — the functions that process data before displaying a template — are organized into files in `uber/site_sections/`, which correspond to the second to last part of the URL for any page. Each Python file in `site_sections` should have a corresponding folder in `uber/templates/`, with page handlers in the Python file corresponding to a file inside the matching folder.

For example, most of our public-facing pages are defined in `uber/site_sections/preregistration.py`. The template that corresponds to the `confirm` function in this file is `uber/templates/preregistration/confirm.html`. The URL for this template would be `https://www.mydomain.com/uber/preregistration/confirm`.

## Configuration and Defining Enum Lists

Configuration options and enums are defined via INI and accessed via the `c` object, e.g., `c.ATTENDEE_BADGE`. Explanations for all config options can be found in `uber/configspec.ini`. For adding fields with a list of options (e.g., a select dropdown), you’ll need to add a section under `[enums]` with a list of variable names and corresponding strings. For actual configuration (i.e., flags that events will want to change), see the Reggie Config Guide link above.

`/development-defaults.ini` provides an example for how to override select config values, which you can do by creating a `/development.ini` file that does not get checked into GitHub. When sections in `[enums]` are redefined, options are *added to* them or change the text on existing options — you cannot remove existing enums defined in configspec.ini, so keep that in mind.

Processing of config happens in `uber/config.py`, which also defines config properties that need to be computed. Note that some types of config options have extra properties defined in the `__getattr__` function — for example, all dates also have `c.BEFORE_DATE` and `c.AFTER_DATE` properties that let you check today’s date against those dates.

The literal value of each enum is an integer computed based on the variable name; for example, the value of `c.ATTENDEE_BADGE` is 51352218. in certain cases, you may want to open an Ubersystem-aware Python REPL (both the MAGFest and MFF repo have Docker containers for this) and print a variable to see its raw output.
