"""Rannoch report: the reporter alone, on a finished run's results (geth report). See harness/run.py."""
import sys

from .run import main

if __name__ == "__main__":
    sys.exit(main(sys.argv[1:] + ["--report_only"]))
