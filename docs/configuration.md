# Ubersystem Configuration

Sideboard uses [ConfigObj](https://configobj.readthedocs.io/en/latest/configobj.html) format INI files and environment variables to configure the server.
Ubersystem (and all other Sideboard plugins, such as event plugins) also use ConfigObj and similar environment variables, but prefixed with their name.

ConfigObj uses [ConfigSpec](https://configobj.readthedocs.io/en/latest/configobj.html#configspec) files to validate the configuration at runtime. Sideboard
and each plugin has a `configspec.ini` file that lists every configuration variable that can be set.

The [Sideboard configspec.ini](https://github.com/magfest/sideboard/blob/main/sideboard/configspec.ini) mostly contains low-level settings such as CherryPy server
configuration, logging settings, and session storage configuration. Most things in this file can be left alone unless you are optimizing or debugging a server.

[Ubersystem's configspec.ini](https://github.com/magfest/ubersystem/blob/main/uber/configspec.ini) contains the vast majority of settings, including the event name,
event dates, t-shirt size options, and much much more.

## Loading Configuration
When Ubersystem starts it looks at environment variables to find its configuration.

| Environment Variable | Default Value | Description |
| SIDEBOARD_CONFIG_FILES | "" | This is an optional list of INI files, separated by semicolons, containing configuration for Sideboard |
| UBERSYSTEM_CONFIG_FILES | "" | This is an optional list of INI files, separated by semicolons, containing configuration for Ubersystem |
| <plugin name>_CONFIG_FILES | "" | Every additional Sideboard plugin can be configured similarly using this variable with their prefix |

In addition to the file-based method, individual settings may be configured using environment variables.

To find the name of a setting simply concatenate the plugin name (or Sideboard) with the configuration path, concatenated with `_`.

For example, the following Sideboard INI file would map to environment variables as shown:
```ini
url_root = /
[cherrypy]
tools.sessions.enabled = True
```

| Environment Variable | Value | Description |
| sideboard_url_root | / | |
| sideboard_cherrypy_tools_sessions_enabled | True | |

Note that `.` becomes `_` and the config paths is joined by underscores.

### Environment Variables

### Configuration Files

## Datatypes

## Important Settings

## Generated Configuration

## Setting Reference