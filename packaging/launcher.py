import sys

from maplehelper.setupwait import report_broken_install, wait_for_setup

wait_for_setup()     # before Qt / numpy load: an update may be replacing them right now

try:
    from maplehelper.app import main  # noqa: E402
except Exception as e:   # noqa: BLE001 - a missing or damaged file of the install (e.g. shiboken6.Shiboken)
    report_broken_install(e)
    sys.exit(1)

sys.exit(main())
