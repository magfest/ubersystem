#!/app/env/bin/python3
from configobj import ConfigObj
import base64
import gzip
import yaml
import os

root = os.environ.get("UBERSYSTEM_ROOT", "/app")
config = os.environ.get("UBERSYSTEM_CONFIG", "[]")
secrets = yaml.load(os.environ.get("UBERSYSTEM_SECRETS", "{}"), Loader=yaml.Loader)


plugins = os.listdir(os.path.join(root, "plugins"))
plugin_configs = {x: [] for x in plugins}
sideboard_configs = []

for plugin in plugins:
    default_config = os.path.join(root, "plugins/", plugin, "development.ini")
    if os.path.isfile(default_config):
        plugin_configs[plugin].append(ConfigObj(default_config))
sideboard_default_config = os.path.join(root, "development.ini")
if os.path.isfile(sideboard_default_config):
    sideboard_configs.append(ConfigObj(sideboard_default_config))

for encoded in yaml.load(config, Loader=yaml.Loader):
    decoded = base64.b64decode(encoded)
    unzipped = gzip.decompress(decoded)
    parsed = yaml.load(unzipped, Loader=yaml.Loader)

    sideboard_config = parsed.get("sideboard", {})
    if sideboard_config:
        sideboard_configs.append(ConfigObj(sideboard_config))

    plugin_config = parsed.get("plugins", {})
    for key, val in plugin_config.items():
        if key in plugin_configs:
            plugin_configs[key].append(ConfigObj(val))
        else:
            print(f"Found config for unknown plugin {key}")

    extra_files = parsed.get("extra_files", {})
    for filename, contents in extra_files.items():
        path = os.path.join(root, filename)
        directory = os.path.dirname(path)
        if not os.path.isdir(directory):
            os.makedirs(directory)
        with open(path, "w") as EXTRA:
            EXTRA.write(contents)

for plugin, configs in plugin_configs.items():
    if configs:
        config = configs[0]
        for override in configs[1:]:
            config.merge(override)
        if plugin in secrets:
            config.merge(ConfigObj(secrets[plugin]))
        config.filename = os.path.join(root, "plugins/", plugin, "development.ini")
        config.write()
        with open(os.path.join(root, "plugins/", plugin, "development.ini"), "r") as CONFIG:
            print(plugin, CONFIG.read())

if sideboard_configs:
    config = sideboard_configs[0]
    for override in configs[1:]:
        config.merge(override)
    if "sideboard" in secrets:
        config.merge(ConfigObj(secrets["sideboard"]))
    config.filename = os.path.join(root, "development.ini")
    config.write()
    with open(os.path.join(root, "development.ini"), "r") as CONFIG:
        print("sideboard", CONFIG.read())