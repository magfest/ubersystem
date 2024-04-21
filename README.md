[![License: AGPL v3](https://img.shields.io/badge/License-AGPL%20v3-blue.svg)](https://www.gnu.org/licenses/agpl-3.0)

# The Ubersystem Project
The Ubersystem Project is a web app written in Python and designed for high
customization to suit any event's needs. It's aimed largely at fandom events
and can track things like registration, events, staffers, groups, dealers,
jobs, game checkouts, etc.

This app was originally developed by [MAGFest](https://magfest.org) as their
internal registration system, named Ubersystem, and is now open source and
available for anyone to use. Eternal thanks to
[Eli Courtwright](https://github.com/EliAndrewC) for tirelessly developing
Ubersystem for over ten years.

# Background
Ubersystem is a single-tenant, single-event system. You must deploy an instance of Ubersystem for each event that you host.

Ubersystem uses configuration files and a plugin mechanism to support customization. Most events end up creating a plugin
with their theming, custom business logic, and other bespoke needs. See [magprime](https://github.com/magfest/magprime)
for a fully-fledged event plugin with many customizations.

Ubersystem has many names! You may hear reference to RAMS (Registration And Management System), Reggie, Uber, and Ubersystem.
These names are all used to refer both to the code in this repository as well as individual events' instantiations of
Ubersystem with their own modifications.

# Installation
## Development Instances (Docker Compose)
Most developers choose to use [docker compose](https://docs.docker.com/compose/) to deploy their local instances.

The [docker-compose.yml](docker-compose.yml) file in the root of this repo will provision a barebones Ubersystem server
with a cherrypy web worker, celery task runner and scheduler, rabbitmq message broker, and postgresql database.

Additionally, it will mount the repository directory into the containers at `/app/plugins/uber` so that code changes will 
immediately be available inside the containers.

To install Ubersystem using docker compose do the following:

1. Install [Docker Desktop](https://docs.docker.com/desktop/), or if on Linux [Docker Engine](https://docs.docker.com/engine/install/)
2. Clone this repository `git clone https://github.com/magfest/ubersystem.git`
3. Enter the repository directory `cd ubersystem`
4. Start the server `docker compose up`

At this point you should see the containers starting up. After everything has launched you can connect to uber by going to:
[http://localhost/](http://localhost/).

On first startup you can create an admin user by navigating to [http://localhost/accounts/insert_test_admin](http://localhost/accounts/insert_test_admin).
After doing this you can log in using `magfest@example.com` as a username and `magfest` as a password.

Now that you have a working instance you can look at the [configuration guide](configuration.md) to start customizing your instance or 
check out the [sample event plugin](https://github.com/magfest/sample-event) to dive deeper into making Ubersystem your own.

| :exclamation: If you didn't get a working instance check out the [troubleshooting guide](docs/troubleshooting.md). |
|---------------------------------------------------------------------------------------------------------------|

## Production Instances
There are many ways to successfully deploy an Ubersystem instance. Currently, MAGFest is using [Amazon ECS](https://aws.amazon.com/ecs/) 
deployed using [this Terraform code](https://github.com/magfest/terraform-aws-magfest). Other groups use Docker Compose for their production
instances.

For large deployments we provide a helm chart for deploying Ubersystem on [Kubernetes](https://kubernetes.io/).

## Setup
After installing Ubersystem, please refer to the [Stripe instructions](docs/stripe.md) to set up immediate payment processing.

## Reference
Here are [some quick reference notes](docs/dbutils.md) on common PostgreSQL tasks.
