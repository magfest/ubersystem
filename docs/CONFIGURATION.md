# Ubersystem Configuration

Ubersystem uses [ConfigObj](https://configobj.readthedocs.io/en/latest/configobj.html) format INI files and environment variables to configure the server.
Event plugins also use ConfigObj and similar environment variables, but prefixed with their name.

ConfigObj uses [ConfigSpec](https://configobj.readthedocs.io/en/latest/configobj.html#configspec) files to validate the configuration at runtime. Ubersystem
and each plugin has a `configspec.ini` file that lists every configuration variable that can be set.

[Ubersystem's configspec.ini](https://github.com/magfest/ubersystem/blob/main/uber/configspec.ini) contains the vast majority of settings, including the event name,
event dates, t-shirt size options, and much much more.

## Loading Configuration
When Ubersystem starts it looks at environment variables to find its configuration.

| Environment Variable | Default Value | Description |
| UBERSYSTEM_CONFIG_FILES | "" | This is an optional list of INI files, separated by semicolons, containing configuration for Ubersystem |
| <plugin name>_CONFIG_FILES | "" | Every additional ubersystem plugin can be configured similarly using this variable with their prefix |

In addition to the file-based method, individual settings may be configured using environment variables.

To find the name of a setting simply concatenate the plugin name with the configuration path, concatenated with `_`.

For example, the following Ubersystem INI file would map to environment variables as shown:
```ini
url_root = /
[cherrypy]
tools.sessions.enabled = True
```

| Environment Variable | Value | Description |
| uber_url_root | / | |
| uber_cherrypy_tools_sessions_enabled | True | |

Note that `.` becomes `_` and the config paths is joined by underscores.

### Environment Variables

### Configuration Files

## Datatypes

## Important Settings

## Generated Configuration

## Setting Reference