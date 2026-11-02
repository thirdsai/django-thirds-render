#!/usr/bin/env python
"""Run the suite: python runtests.py (mocked) or THIRDS_LIVE=1 python runtests.py tests.test_live"""
import os
import sys

import django
from django.conf import settings
from django.test.utils import get_runner

if __name__ == "__main__":
    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "tests.settings")
    django.setup()
    runner = get_runner(settings)(verbosity=2)
    sys.exit(bool(runner.run_tests(sys.argv[1:] or ["tests.test_mocked"])))
