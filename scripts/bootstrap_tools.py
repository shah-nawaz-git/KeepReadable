import sys

from keepreadable.cli import main

if __name__ == "__main__":
    raise SystemExit(main(["bootstrap", *sys.argv[1:]]))
