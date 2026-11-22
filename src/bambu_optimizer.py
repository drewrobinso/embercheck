#!/usr/bin/env python3
"""Compatibility shim: Bambu Print Optimizer (1.x) was renamed to EmberCheck in 1.4.2.
Old post-processing lines that call bambu_optimizer.py keep working; new ones call embercheck.py."""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from embercheck import main  # noqa: E402
if __name__ == '__main__':
    sys.exit(main())
