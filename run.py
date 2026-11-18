"""PyInstaller entry point."""
import sys

from island.app import main

raise SystemExit(main(sys.argv[1:]))
