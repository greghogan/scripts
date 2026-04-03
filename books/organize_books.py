#!/usr/bin/env python

# To create a folder of test files matching the filenames of a directory of books:
#   find path/to/books -type f -exec bash -c 'echo "$1" > "test/$(basename "$1")"' -- {} \;

import os
import sys

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
if SCRIPT_DIR not in sys.path:
    sys.path.insert(0, SCRIPT_DIR)

from lib.main import main


if __name__ == "__main__":
    main()
