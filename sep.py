from __future__ import unicode_literals
from sys import argv

from uber.sep_commands import _entry_points


def print_usage():
    print('usage: {} ENTRY_POINT_NAME ...'.format(argv[0]))
    print('known entry points:')
    print('\n'.join(['    {}'.format(ep) for ep in sorted(_entry_points)]))


def run_plugin_entry_point():
    if len(argv) < 2:
        print_usage()
        exit(1)

    if len(argv) == 2 and argv[1] in ['-h', '--help']:
        print_usage()
        exit(0)

    del argv[:1]  # we want the entry point name to be the first argument

    ep_name = argv[0]
    if ep_name not in _entry_points:
        print('no entry point with name {!r}'.format(ep_name))
        exit(2)

    _entry_points[ep_name]()


if __name__ == '__main__':
    run_plugin_entry_point()
