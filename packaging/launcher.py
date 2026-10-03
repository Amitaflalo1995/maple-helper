import sys

from maplehelper.setupwait import report_broken_install, wait_for_setup

wait_for_setup()     # before Qt / numpy load: an update may be replacing them right now

try:
    from maplehelper.app import main  # noqa: E402
except Exception as e:   # noqa: BLE001 - a missing/damaged file (reinstall helps), or another startup error
    report_broken_install(e)
    sys.exit(1)

try:
    sys.exit(main())
except Exception as e:   # noqa: BLE001 - never a bare traceback window: say what happened, keep the log
    report_broken_install(e)
    sys.exit(1)
