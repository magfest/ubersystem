Setting up Ubersystem to run on Vagrant
==================

THESE INSTRUCTIONS ARE OBSOLETE
===============================

THIS FILE IS NOW OBSOLETE.  IT WILL BE REMOVED SOON.
instead of doing this, use the instructions at https://github.com/magfest/ubersystem-deploy

ORIGINAL INSTRUCTIONS
=====================

Windows instructions, if you're on Linux/etc the process will be similar.

[Vagrant](http://www.vagrantup.com/) is a great way to provide portable development environments by letting you install a local VM and have it automatically configured with all of the software and dependencies you need to start developing.

## What you'll need
* [Git](http://git-scm.com/) to check out this repo and to provide SSH.
* [TortoiseGit](https://code.google.com/p/tortoisegit/) or [GitHub for Windows](https://windows.github.com/) to use as an interface for Git. You can also use any other git tool you like, or simply use the command line.
* [VirtualBox](https://www.virtualbox.org/wiki/Downloads) for running your development VM.
* [Vagrant](http://www.vagrantup.com/downloads.html) itself.

## Fork ubersystem (optional)
Forking ubersystem allows you to develop on your own and then submit pull requests. It's useful if you want to develop a custom system where not everything will be merged upstream.
1. Make an account (or log in to your existing account) on [GitHub](https://github.com/).
2. Go to [MAGFest Ubersystem](https://github.com/magfest/ubersystem) and click the "Fork" button at the top right of the page.
3. Clone your new repo, which will be at ``https://github.com/<YOUR-USERNAME>/magfest``.

## Clone ubersystem
1. Create the folder that you want ubersystem to live in.
2. If you're using TortoiseGit, right-click inside the folder and select "Git Clone." Paste the GitHub URL to the repository (e.g., ``https://github.com/magfest/ubersystem``) and press OK.
3. If you're using GitHub for Windows, simply start GfW, log in to GitHub, and click the "+" button in the upper-left hand corner. Select "Clone" and set the cloning directory.

## Running Vagrant
Open a cmd or bash prompt run as an administrator.

Change into the ``ubersystem`` directory that was created when you cloned your repo, and type ``vagrant up``.  This does a bunch of different things:
* Downloads a VirtualBox image of an Ubuntu server from the internet.
* Starts up the VM and installs all necessary OS dependencies.
* Sets up a Python virtualenv with all of the necessary Python packages needed to run Uber.

Now that you have your VM, the only thing left to do is log into your server and start Uber.

If you're on Windows, make sure Git is in your PATH. Use this if you're not sure how:
http://blog.countableset.ch/2012/06/07/adding-git-to-windows-7-path/

Next, run

```bash
vagrant ssh
```

## Setting up the database
When running uber on a testing server, you'll probably want some data to work with. Ubersystem comes with a large (10k+) set of realistic test data. This data was created from MAGFest 12's attendee database by scrubbing personal information and swapping first and last names around.

To add the test data to your local server, run the following command after sshing into vagrant:
```bash
sep import_uber_test_data
```

For staging and production servers, you may not want this data, but you'll definitely want a starting admin account. To create this account, run:
```bash
sep insert_admin
```

This account, by default, has a login of "magfest@example.com" and the password "magfest".

Finally, there are some cases during development where you simply want to erase the current database and start anew. To do this, run:
```bash
sep reset_uber_db
```

Note that this command only works if DEV_BOX is turned on - this is to prevent accidentally deleting important data on production servers.

## Running ubersystem

After logging in and setting up your database, you can run the following command to run start the Ubersystem server:

```bash
run_server
```

After running this command, you can go to http://localhost:8282/ and log in with the starting admin account credentials.

Now you're ready to do development; every time you edit one of the Python files that make up Uber, the process will restart automatically, so you'll see the change as soon as you refresh your browser.  The only thing to watch out for is that if you make a syntax error, the process will stop altogether since it can't restart without being valid.  In that case you'll have to re-run the above command to re-start the server (after fixing your syntax error).

If you want to run the server in the background to free up your ssh session for other commands, use Ctrl-Z to suspend it and then run

```bash
bg
```

to run the server in the background.


Vagrant Troubleshooting:
==========================

1. Shared folders are very slow on Windows. Don't be surprised that things run a bit slower.

2. You probably should use the virtualbox application to increase the CPU and Memory size of the image to make it run smoother.  4CPU and 4GB of mem is a good start.

3. If VirtualBox hangs on startup with a message about "Clearing port forwarding", it's misleading and probably having a silent issue with the shared folder mount (https://github.com/mitchellh/vagrant/issues/3139)

A workaround for this is to install Powershell v3, which seems to fix it. http://www.microsoft.com/en-us/download/details.aspx?id=34595