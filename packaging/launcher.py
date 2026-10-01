import sys

from maplehelper.setupwait import wait_for_setup

wait_for_setup()     # before Qt / numpy load: an update may be replacing them right now

from maplehelper.app import main  # noqa: E402

sys.exit(main())
