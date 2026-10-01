import sys

from .setupwait import wait_for_setup

wait_for_setup()     # before Qt / numpy load (see setupwait.py)

from .app import main  # noqa: E402

sys.exit(main())
