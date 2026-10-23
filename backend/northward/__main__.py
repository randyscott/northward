import sys

from northward.cli import main

# Guarded: worker processes started with "spawn" import this module too.
if __name__ == "__main__":
    sys.exit(main())
