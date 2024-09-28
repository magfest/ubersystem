#!/app/env/bin/python3
import argparse
import pathlib
import tempfile
import yaml
import os

parser = argparse.ArgumentParser(
    prog='make_config',
    description='Generates ubersystem config files from compressed environment variables'
)
parser.add_argument("--repo", required=True, help="Optional git repo to pull config from, used for development")
parser.add_argument("--paths", required=True, nargs="*", help="Configuration paths to use when loading from git repo")
parser.add_argument("--environment", required=False, help="Create an environment file that will tell uber where to find all generated configs")
args = parser.parse_args()

repo_config = []
with tempfile.TemporaryDirectory() as temp:
    print(f"Cloning config repo {args.repo} into {temp}")
    os.system(f"git clone --depth=1 {args.repo} {temp}")
    files = []
    for path in args.paths:
        print(f"Loading files from {path}")
        parts = pathlib.PurePath(path).parts
        for idx, part in enumerate(parts):
            full_path = os.path.join(temp, *parts[:idx+1])
            files.extend([os.path.join(full_path, x) for x in os.listdir(full_path) if x.endswith(".yaml")])
    for filename in files:
        print(f"Loading config from {filename}")
        with open(filename, "rb") as FILE:
            repo_config.append(yaml.safe_load(FILE))

secrets = os.environ.get("UBERSYSTEM_SECRETS", None)
if secrets:
    repo_config.append({
        "plugins": yaml.safe_load(secrets)
    })

plugin_configs = {}
for parsed in repo_config:
    plugin_config = parsed.get("plugins", {})
    for key, val in plugin_config.items():
        if not key in plugin_configs:
            plugin_configs[key] = []
        plugin_configs[key].append(val)

def merge_values(a, b):
    if isinstance(a, dict) and isinstance(b, dict):
        return {key: merge_values(a.get(key, None), b.get(key, None)) for key in set(a.keys()).union(set(b.keys()))}
    if b is None:
        return a
    return b

def merge_configs(configs):
    base = {}
    for config in configs:
        for key, val in config.items():
            if key in base:
                base[key] = merge_values(base[key], val)
            else:
                base[key] = val
    return base

def quote_string(string):
    string = str(string).strip()
    if ',' in string or '\n' in string:
        string = f"'''{string}'''"
    return string

def serialize_config(config, depth=1):
    doc = ""
    for key, val in sorted(config.items(), key=lambda x: x[0]):
        key = quote_string(key)
        if not isinstance(val, dict):
            if val is None:
                doc += f"{key} = \n"
            elif isinstance(val, list):
                doc += f"{key} = " + ", ".join([quote_string(x) for x in val])
                if len(val) < 2:
                    doc += ","
                doc += "\n"
            else:
                doc += f"{key} = {quote_string(val)}\n"
    for key, val in sorted(config.items(), key=lambda x: x[0]):
        if isinstance(val, dict):
            doc += f'\n{"["*depth}{key.strip()}{"]"*depth}\n'
            doc += serialize_config(val, depth=depth+1)
    return doc
                


for plugin, configs in plugin_configs.items():
    print(f"Saving {plugin} config to {plugin}.ini")
    config = merge_configs(configs)
    doc = serialize_config(config)
    with open(f"{plugin}.ini", "w") as file:
        file.write(doc)

print("Use the following environment variables to load this config:")
for plugin in plugin_configs:
    print(f"{plugin.upper()}_CONFIG_FILES={plugin}.ini")

if args.environment:
    with open(args.environment, "w") as file:
        for plugin in plugin_configs:
            existing = os.environ.get(f"{plugin.upper()}_CONFIG_FILES", "")
            path = pathlib.Path(f"{plugin}.ini").resolve()
            if existing:
                file.write(f'export {plugin.upper()}_CONFIG_FILES="{path};{existing}"\n')
            else:
                file.write(f'export {plugin.upper()}_CONFIG_FILES="{path}"\n')

extra_file_config = {}
for parsed in repo_config:
    extra_files = parsed.get("extra_files", {})
    extra_file_config.update(extra_files)

for filename, content in extra_file_config.items():
    print(f"Writing extra_file {filename}")
    parent_dir = os.path.dirname(filename)
    if not os.path.isdir(parent_dir):
        os.makedirs(parent_dir)
    with open(filename, "w") as filehandle:
        filehandle.write(content)
            