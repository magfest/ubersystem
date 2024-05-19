# Developers Guide
## Local Installation
The first step to writing new features or bug fixes for Ubersystem is to install a copy of the server on your local machine. This allows you to quickly see your changes in action before you [submit a pull request](https://docs.github.com/en/pull-requests/collaborating-with-pull-requests/proposing-changes-to-your-work-with-pull-requests/creating-a-pull-request).

### Running Ubersystem with Docker Compose
Ubersystem is composed of several different services communicating with each other. The best and easiest way to run and manage these services locally is through [Docker Compose](https://docs.docker.com/compose/). Docker Compose will create isolated containers for each service and allow them to talk with each other.

The [docker-compose.yml](docker-compose.yml) file in the root of this repo will provision the core Ubersystem server with all the required services: a CherryPy web worker, a Celery task runner and scheduler, a RabbitMQ message broker, and a PostgreSQL database.

Additionally, it will mount this repository directory into the containers as a volume -- each container will mount the files inside `/app/plugins/uber`. This allows code changes you make on your computer to update inside the containers without rebuilding them.

### The Command Line
Throughout this guide and elsewhere in our documentation, we will be providing commands to run in a command line terminal. If you aren't familiar with the command line, it is a text-based interface that allows you to quickly run complex operations by communicating directly with programs. Depending on your operating system, you'll likely run commands using either [Bash](https://www.gnu.org/software/bash/) (Linux), [Zsh](https://zsh.sourceforge.io/) (Mac), or [Command Prompt/CMD](https://learn.microsoft.com/en-us/windows-server/administration/windows-commands/windows-commands) (Windows).

Providing command-line commands lets us give specific instructions that won't become outdated with software updates. Many applications will also have graphical interfaces that you can use as a convenience, and we encourage you to explore those when you are comfortable with the basics.

### Prerequisites
You will need the following programs installed to run Ubersystem using Docker Compose:

- [Docker Desktop](https://docs.docker.com/desktop/), or [Docker Engine](https://docs.docker.com/engine/install/) if you are on Linux. This is the program that actually builds and runs the containers.
- [Git](https://git-scm.com/), which will let you download and manage the code from this repository.
- A code editor of your choice. If you don't already have a preference, we recommend [VSCode](https://code.visualstudio.com/) as it is free, easy to learn, and has many useful extensions. It also comes with [source control tools](https://code.visualstudio.com/docs/sourcecontrol/overview) that provide a convenient interface for using Git.

### Instructions

1. Clone this repository using Git by running `git clone https://github.com/magfest/ubersystem.git`. This will download the repository's code into a new folder named `ubersystem`.
2. Enter the new folder with `cd ubersystem`.
3. Start the server by running `docker compose up`.

At this point you should see logs showing the containers downloading, compiling, and starting up. Once the line `ENGINE Bus STARTED` has printed, the server is ready and you can connect to Uber by browsing to
[http://localhost/](http://localhost/) in your preferred browser.

On first startup you can create an admin user by navigating to [http://localhost/accounts/insert_test_admin](http://localhost/accounts/insert_test_admin).
After doing this you can log in using `magfest@example.com` as a username and `magfest` as a password.

| :exclamation: If you didn't get a working instance check out the [troubleshooting guide](troubleshooting.md). |
|---------------------------------------------------------------------------------------------------------------|

## Adding Custom Config & Plugins
Ubersystem uses a large array of configuration options to change the event name, event dates, t-shirt size options, and much much more. These options are defined in a configuration file.

Beyond this configuration, events can write custom plugins that override templates with custom text or add new features, like badge add-ons specific to that event. If your event uses a custom plugin, you will need to download and install it as a plugin for Uber to make sure your code changes behave the way you want for your event.

### Configuration
The default configuration options, plus explanations of what each config option does, can be found in [configspeci.ini](configspec.ini).

You should *only* edit configspec.ini if you are adding new config options to Uber. To set your own config, you will need to define a new configuration file that contains just the variables you want to "override" the default values on.

If you're just getting started and not working for a specific event, you can use the example config overrides below. Create a new text file in the root of this repo called `uber.ini`, then copy and paste the block below and edit it to whatever values you want.

```ini
event_year = 2025

[dates]
# YYYY-MM-DD HH
prereg_open = 2024-09-15 14
dealer_reg_start = 2024-08-11 20
dealer_reg_shutdown = 2024-08-11 21
```

After creating your config file, you will need to instruct Docker Compose to use it. See [loading custom config and plugins](#loading-custom-config-and-plugins) for instructions on how to do this.

For more advanced information on how Ubersystem's config works, including instructions for downloading and compiling config for specific events, check out the [config guide](configuration.md).

### Custom Plugins
Ubersystem can load one or more plugins that can override many core functions and behavior. These plugins will have their own repository, and in most cases will correspond 1:1 with each event (e.g., MAGStock will use a single `magstock` plugin for its custom functionality).

Custom plugins will usually be hosted on GitHub by an organization run by the event, e.g., [the plugin for Super MAGFest](https://github.com/magfest/magprime) is hosted in MAGFest's [GitHub organization](https://github.com/magfest/).

You'll download the custom plugin repository the same way you download this repository, using `git clone`. One thing you'll want to make sure of is to download both repositories to the _same directory_, rather than downloading the custom plugin inside the `ubersystem` directory. If you still have the terminal open from the installation instructions above, you can use `Ctrl-` or `Cmd-C` to exit Docker Compose and run `cd ../` to quickly travel "up" a directory before running `git clone`.

When cloning the repository with Git (`git clone REPOURL`), your repo URL can look like either `https://github.com/magfest/magprime` (copied from your browser URL bar) or `https://github.com/magfest/magprime.git` (copied from the "Code" dropdown on GitHub).

| :exclamation: If cloning a repo with non-alphanumeric characters, like hyphens, you should rename the base repo folder to convert them to underscores. E.g., `mff-rams-plugin` should be renamed to `mff_rams_plugin`. |
|---------------------------------------------------------------------------------------------------------------|

To enable your plugin, you'll follow the loading instructions below. First, though, make sure your plugin has a config override file. You can [download the file from a config repo](configuration#generated-configuration) (if applicable) or create a blank text file in the root folder of the plugin. It should be named after the plugin itself, e.g., `/magprime/magprime.ini`.

### Loading Custom Config and Plugins
The last step for loading custom config or plugins (or both) is to tell Docker Compose to use them. There are a few ways to do this, but here we'll cover how to use environment variables defined in an `.env` file.

You may notice that no `.env` file exists in this repository -- this is intended. Both config files and the .env file do not get uploaded (or "checked into") Git. This allows you to set up your config and plugins without affecting anyone else's setup.

Instead, we have an `.env.example` file, located in the root of this repository. Copy this file and paste it as a new file in the same directory, then rename the new file to `.env`. In this file, you'll have two lines to edit:

- On the line `PLUGIN_NAME=yourplugin`, replace `yourplugin` with your plugin folder's name in its normal case, e.g., `magprime`.
- On the line `YOURPLUGIN_CONFIG_FILES=${PLUGIN_NAME}`, change `YOURPLUGIN` to an all-caps version of your plugin folder's name, e.g., `MAGPRIME`.

If you used these instructions to set up your config file(s) (`uber.ini` for this repository, plus `yourplugin.ini` for any custom plugins), that's all you need to change. The next time you use `docker compose up`, your plugin and custom config will be loaded!
