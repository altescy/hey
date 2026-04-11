import argparse

from hey.version import VERSION


def build_parser(*, prog: str | None = None) -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog=prog, description="Hey is a workflow engine for Python.")
    parser.add_argument("--version", action="version", version=f"%(prog)s {VERSION}")
    return parser


def main(prog: str | None = None) -> None:
    parser = build_parser(prog=prog)
    parser.parse_args()
