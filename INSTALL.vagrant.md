Setting up Ubersystem to run on Vagrant
==================
Windows instructions, if you're on linux/etc the process will be similar.

[Vagrant](http://www.vagrantup.com/) is a great way to provide portable development environments by letting you install a local VM and have it automatically configured with all of the software and dependencies you need to start developing.  If you're already running Linux, we recommend you just develop locally, so this section assumes you are using Windows.  Here's what you'll need to install to get your dev environment up and running:
* [TortoiseGit](https://code.google.com/p/tortoisegit/) for checking out this repo. You can also use any other git tool you like.
* [VirtualBox](https://www.virtualbox.org/wiki/Downloads) for running your development VM
* [Vagrant](http://www.vagrantup.com/downloads.html) itself
* [Putty](http://www.chiark.greenend.org.uk/~sgtatham/putty/download.html) for SSH-ing into your development machine once it's up and running

First, use TortoiseGit to check out this repo.  It's probably a good idea to fork this repo and then clone your fork, to do that:
* make an account (or log in to your existing account) on [GitHub](https://github.com/)
* go to https://github.com/magfest/ubersystem and click the "Fork" button at the top right of the page
* tell TortoiseGit to clone your new repo, which will be at ``https://github.com/<YOUR-USERNAME>/magfest``

Next open a DOS prompt run as an administrator.  go to Start->Accessories->Command Prompt, right click, run as administrator

Change into the ``magfest`` directory that was created when you cloned your repo, and type ``vagrant up``.  This does a bunch of different things:
* downloads a VirtualBox image of an Ubuntu server from the internet
* starts up the VM and installs all necessary OS dependencies
* creates a database filled with test data
* sets up a Python virtualenv with all of the necessary Python packages needed to run Uber

Now that you have your VM, the only thing left to do is log into your server and start Uber.  First, make sure Git is in your Windows PATH. Use this if you're not sure how:
http://blog.countableset.ch/2012/06/07/adding-git-to-windows-7-path/

Next, run

```bash
vagrant ssh
```

Once you've logged in, you can run the following command to run start the Ubersystem server:

```bash
run_server.py
```

After running this command, you can go to http://localhost:8282/ and log in with the email address "magfest@example.com" and the password "magfest".

Now you're ready to do development; every time you edit one of the Python files that make up Uber, the process will restart automatically, so you'll see the change as soon as you refresh your browser.  The only thing to watch out for is that if you make a syntax error, the process will stop altogether since it can't restart without being valid.  In that case you'll have to re-run the above command to re-start the server (after fixing your syntax error).

If you want to run the server in the background to free up your ssh session for other commands, use Ctrl-Z to suspend it and then run

```bash
bg
```

to run the server in the background.

Vagrant troubleshooting notes:
==========================

Note1: shared folders are very slow on Windows. Don't be suprised that things run a bit slower.

Note2: you probably should use the virtualbox application to increase the CPU and Memory size of the image to make it run smoother.  4CPU and 4GB of mem is a good start.

Note3: If virtualbox hangs on startup with a message about "Clearing port forwarding", it's misleading and probably having a silent issue with the shared folder mount (https://github.com/mitchellh/vagrant/issues/3139)

A workaround for this is to install Powershell v3, which seems to fix it. http://www.microsoft.com/en-us/download/details.aspx?id=34595
