"""The explicit development launcher."""

import argparse
from collections.abc import Sequence


def main(argv: Sequence[str] | None = None) -> None:
    parser = argparse.ArgumentParser(
        prog="expose-interface",
        description="Export ordinary Python functions as command line programs.",
    )
    parser.add_argument("--version", action="version", version="%(prog)s 0.1.0")
    parser.parse_args(argv)
    parser.print_help()


if __name__ == "__main__":
    main()
