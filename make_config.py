#!/app/env/bin/python3
from configobj import ConfigObj
import tempfile
import argparse
import pathlib
import base64
import gzip
import yaml
import sys
import os

root = os.environ.get("UBERSYSTEM_ROOT", "/app")
config = os.environ.get("UBERSYSTEM_CONFIG", "[]")
secrets = yaml.load(os.environ.get("UBERSYSTEM_SECRETS", "{}"), Loader=yaml.Loader)

parser = argparse.ArgumentParser(
    prog='make_config',
    description='Generates ubersystem config files from compressed environment variables'
)
parser.add_argument("--repo", required=False, help="Optional git repo to pull config from, used for development")
parser.add_argument("--servername", help="Config key in servers.yaml for this instance")
parser.add_argument("--environment", help="Which environment in servers.yaml to use")
parser.add_argument("--overwrite", help="Overwrite an existing development.ini if it exists", action="store_true")
args = parser.parse_args()

if not args.overwrite and os.path.exists("development.ini"):
    sys.exit("development.ini already exists. Use --overwrite to replace it.")

if args.repo:
    repo_config = []
    with tempfile.TemporaryDirectory() as temp:
        print(f"Cloning config repo {args.repo} into {temp}")
        os.system(f"git clone --depth=1 {args.repo} {temp}")
        files = []
        with open(f"{temp}/servers.yaml") as FILE:
            environments = yaml.load(FILE, Loader=yaml.Loader)
        paths = environments.get(args.environment, {}).get(args.servername, {}).get("config_paths", [])
        for path in paths:
            print(f"Loading files from {path}")
            parts = pathlib.PurePath(path).parts
            for idx, part in enumerate(parts):
                full_path = os.path.join(temp, *parts[:idx+1])
                files.extend([os.path.join(full_path, x) for x in os.listdir(full_path) if x.endswith(".yaml")])
        for filename in files:
            print(f"Loading config from {filename}")
            with open(filename, "rb") as FILE:
                config_data = FILE.read()
            zipped = gzip.compress(config_data)
            encoded = base64.b64encode(zipped)
            repo_config.append(encoded)
    config = yaml.dump(repo_config, Dumper=yaml.Dumper, encoding="utf8")

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
    for override in sideboard_configs[1:]:
        config.merge(override)
    if "sideboard" in secrets:
        config.merge(ConfigObj(secrets["sideboard"]))
    config.filename = os.path.join(root, "development.ini")
    config.write()
    with open(os.path.join(root, "development.ini"), "r") as CONFIG:
        print("sideboard", CONFIG.read())
