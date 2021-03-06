#!/usr/bin/env python
from __future__ import absolute_import, print_function

import os
import sys

from . import config
from . import x11

try:
    from subprocess import DEVNULL  # py3k
except ImportError:
    DEVNULL = open(os.devnull, 'wb')


def available_configs():
    '''
    Search for available image/config file definitions
    '''
    cfgfiles = config.config_files()
    imagesAvail = [os.path.basename(fn).split('.')[0] for fn in cfgfiles]
    return imagesAvail


def parse_config_volumes(cfg, extra_args=None, cmdline=''):
    # i/o volumes
    # Check whether there is any to mount
    # Exception case is the 'io' directory, which is always present; it is just
    #  escaped during the loop and treated after.
    # Also, for paths (on container's side) not starting with a slash '/'
    #  it will be treated as a new option for the command line. For example,
    #  a volume section like the following:
    # '''
    # [volumes]
    # /products = $PWD/products
    # ingredients = 'what to feed app with'
    # '''
    # will assemble a command-line with a volume mount '$PWD/products' to
    # '/products', but 'ingredients' will be a new option for command-line.

    extra_args = extra_args or []

    for on_container, on_host in cfg['volumes'].items():
        d = on_container
        h = on_host
        _ddir = None
        _hdir = None
        if d != 'io' and d.strip() != '':
            if d[0] == '/':
                # Again: if "key" begins with '/' it is a real path, simplest case
                _ddir = d
                _hdir = os.path.abspath(os.path.expandvars(h))
            else:
                # If it does *not* begin with a '/' it is meant to be a
                # command line argument.
                # We will handle this argument manually here, because 'argparse'
                # is not actually designed for this "dynamic options".
                #
                # Side note: one option would be to "add-and-read" the argument
                # from the command line parser, this would help in handling
                # whenever the argument (required) is missing from the actual
                # command line. Below is the entry to the parser to be used
                # if that is the case; for the time being though, I'll stick
                # with the totally manual processing...
                # ```
                # if parser:
                #     _arg = '--' + d
                #     parser.add_argument(_arg, dest='arg_vol', required=True, nargs=1, help=h)
                # ```
                import re

                # 'jump' flag is used to escape a loop iteration whenever the
                # current and next iterations are bounded; it will happen
                # when '=' between option and argument are missing
                jump = False

                for i, arg in enumerate(extra_args):
                    if jump:
                        jump = False
                        continue

                    # I expect an command line argument of the form '--key'
                    # for "key" in the config file
                    expected_arg = '--' + d
                    _match = re.match('^'+expected_arg, arg)
                    if _match is None:
                        print("Error: Non recognised option '{}'".format(arg),sys.stderr)
                        continue
                    assert _match.pos == 0

                    # See if argument was given with a '=' signal or space separated.
                    if len(arg) == len(expected_arg):
                        h = extra_args[i+1]
                        _hdir = os.path.abspath(os.path.expandvars(h))
                        _ddir = '/'+d
                        jump = True
                    else:
                        assert arg[len(expected_arg)] == '='
                        h = arg.split('=')[1]
                        _hdir = os.path.abspath(os.path.expandvars(h))
                        _ddir = '/'+d

                if _ddir is None or _hdir is None:
                    print("Error: argument for '{}' not given".format(d), file=sys.stderr)
                    return False
                cmdline += ' -v {0}:{1}'.format(_hdir, _ddir)

    return cmdline


def main(argv):
    # Base command-line
    cmdline = 'docker run --rm'

    import argparse
    parser = argparse.ArgumentParser(description='Interface for Docker containers.')
    parser.add_argument('-w', '--io', dest='io_dir', default=None,
                        help="directory to use for files exchange with container (inside container it is '/work'.")
    parser.add_argument('--nox', dest='without_x11', action='store_true',
                        help='do *not* export graphical interface (x11) from the container to host (*do* export by deafult)')
    # DETACHED mode. If not asked for, later we will add '-it' to the command line
    parser.add_argument('-d', dest='detached', action='store_true',
                        help='runs non-interactively (detached mode)')
    # INIT SCRIPT; we have to put here a .rc like file to init the container's Bash
    # parser.add_argument('-f','--file',dest='filename',
    #                     help='filename (found inside io-dir) to argument the container entrypoint')
    parser.add_argument('-n', '--dry-run', dest='dry_run', action='store_true',
                        help="don't run the container, just print the command-line instead")
    parser.add_argument('-l', '--list', dest='list', action='store_true',
                        help='print list of preset images')

    args, _ = parser.parse_known_args()

    if args.list:
        print('List of available/preset images:')
        configs = available_configs()
        configs.sort()
        for im in configs:
            print('- {}'.format(im))
        return os.EX_CONFIG

    parser.add_argument('image',
                        help="name of the image to run. See '-l' for a preset list.")

    args, _ = parser.parse_known_args()

    # Arguments -- options or positional -- after the image name are
    # *not* parsed; they are left there for the container to handle (if it does)
    pos_image_arg = sys.argv.index(args.image)
    app_arguments = sys.argv[pos_image_arg+1:]
    args_to_parse = sys.argv[1:pos_image_arg+1]

    args, extra_args = parser.parse_known_args(args_to_parse)

    # read CONFIG file; if any for this image
    cfg = config.main(args.image)

    cmdline = parse_config_volumes(cfg, extra_args, cmdline)

    if not cmdline:
        return os.EX_DATAERR

    if not args.detached:
        cmdline += ' -it'

    # If IO dir was given, map it to "/work" inside the container
    #
    if args.io_dir:
        io_dir = os.path.abspath(args.io_dir)
        cmdline += ' -v {0}:{1}'.format(io_dir, '/work')

    # option for accessing the x11
    if not args.without_x11:
        _x11 = '/tmp/.X11-unix'
        _dsp = x11.get_DISPLAY()
        cmdline += ' -v {0}:{1} -e DISPLAY={2}'.format(_x11, _x11, _dsp)

    # option for port mappings
    if len(cfg['ports'].keys()) > 0:
        for p_cont, p_host in cfg['ports'].items():
            cmdline += ' -p {0}:{1}'.format(p_host, p_cont)

    # image name in DockerHub
    i_cfg = cfg['main'].get('image')
    image = i_cfg if i_cfg is not '' else args.image

    cmdline += ' {0} '.format(image)

    # Extra, container's problem arguments:
    cmdline += ' '.join(app_arguments)

    if args.dry_run:
        print("#", '-'*(len(cmdline)-1))
        print(cmdline)
        print("#", '-'*(len(cmdline)-1))
    else:
        os.system(cmdline)

    return os.EX_OK
