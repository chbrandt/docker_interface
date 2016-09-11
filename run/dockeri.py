#!/usr/bin/env python
import os
import sys

def available_configs():
    '''
    Search for available image/config file definitions
    '''
    import os
    import config
    cfgfiles = config.config_files()
    imagesAvail = [ os.path.basename(fn).split('.')[0] for fn in cfgfiles ]
    return imagesAvail

def parse_config_volumes(cfg, parser=None, cmdline=''):
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

    known_args, extra_args = parser.parse_known_args()

    for on_container,on_host in cfg['volumes'].items():
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
                # whenever the argument (required) is missing from the actually
                # command line. Below is the entry to the parser to be used
                # if that is the case; for the time being though, I'll stick
                # with the totally manual processing...
                # ```
                # if parser:
                #     _arg = '--' + d
                #     parser.add_argument(_arg, dest='arg_vol', required=True, nargs=1, help=h)
                # ```
                import re

                # 'jump' flag is used to escape a loop whenever the current and next
                # iterations are bounded; it will happen when '=' between option
                # and argument is *not* used
                jump = False

                for i,arg in enumerate(extra_args):
                    if jump:
                        jump = False
                        continue

                    # I expect an command line argument of the form '--key'
                    # for "key" in the config file
                    expected_arg = '--' + d
                    _match = re.match('^'+expected_arg,arg)
                    if _match is None:
                        print >> sys.stderr, "Error: Non recognised option '{}'".format(arg)
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
                    print >> sys.stderr, "Error: argument for '{}' not given".format(d)
                    return False
                cmdline += ' -v {0}:{1}'.format(_hdir,_ddir)

    return parser,cmdline


def main(argv):
    # Base command-line
    cmdline = 'docker run'


    import argparse
    parser = argparse.ArgumentParser(description='Interface for Docker containers.')

    parser.add_argument('-w','--io',dest='io_dir',default=None,
                        help='host directory to use for files I/O with container')
    parser.add_argument('-x',dest='with_x11',action='store_true',
                        help='route x11 from the container?')
    parser.add_argument('-d', dest='detached', action='store_true',
                        help='runs non-interactively (detached mode)')
    # parser.add_argument('-f','--file',dest='filename',
    #                     help='filename (found inside io-dir) to argument the container entrypoint')

    parser.add_argument('-n','--dry-run', dest='dry_run', action='store_true',
                        help="don't run the container, just print the command-line instead")
    parser.add_argument('-l','--list', dest='list', action='store_true',
                        help='print preset list of images')

    args = parser.parse_known_args()
    args = args[0]

    if args.list:
        print 'List of available/preset images:'
        for im in available_configs():
            print '- {}'.format(im)
        return os.EX_CONFIG

    parser.add_argument('image', #choices=available_configs(),
                        help="name of the image to run. See '-l' for a preset list.")

    args = parser.parse_known_args()
    args = args[0]
    # read config (file) for asked image
    import config
    cfg = config.main(args.image)

    out = parse_config_volumes(cfg, parser, cmdline)
    if not out:
        return os.EX_DATAERR
    parser,cmdline = out

    # If no IO dir was given, it takes the default one
    iodir_cfg = cfg['volumes']['io'] if args.io_dir is None else args.io_dir
    iodir_cfg = os.path.abspath(iodir_cfg)
    cmdline += ' -v {0}:{1}'.format(iodir_cfg,'/work/io')

    # option for accessing the x11
    if args.with_x11:
        import x11
        _x11 = '/tmp/.X11-unix'
        _dsp = x11.get_DISPLAY()
        cmdline += ' -v {0}:{1} -e DISPLAY={2}'.format(_x11,_x11,_dsp)

    # option for port mappings
    if len(cfg['ports'].keys()) > 0:
        for p_cont,p_host in cfg['ports'].items():
            cmdline += ' -p {0}:{1}'.format(p_host,p_cont)

    # image name in DockerHub
    i_cfg = cfg['main'].get('image')
    image = i_cfg if i_cfg is not '' else args.image

    cmdline += ' {0}'.format(image)
    # if args.filename is not None:
    #     cmdline += ' {0}'.format(args.filename)

    if args.dry_run:
        print "#",'-'*(len(cmdline)-1)
        print cmdline
        print "#",'-'*(len(cmdline)-1)
    else:
        import shlex, subprocess
        cmdline = shlex.split(cmdline)
        p = subprocess.Popen( cmdline,
                              stdout=sys.stdout,
                              stderr=sys.stderr)
        pid = p.pid
        print "#",'-*-'*len(cmdline)
        print "Container '{}' from image {} is running".format('nameit',image)
        print "The parent's PID is: {}".format(pid)
        print "#",'-*-'*len(cmdline)

    return os.EX_OK
# ---
out = main(sys.argv[1:])
if out == os.EX_CONFIG:
    sys.exit(os.EX_OK)
sys.exit(out)
