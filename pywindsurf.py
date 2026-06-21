#!/usr/bin/env python3
"""Wrapper to run pywindsurf CLI directly from source."""
import sys
from pywindsurf.pywindsurf import main

if __name__ == '__main__':
    sys.exit(main())
