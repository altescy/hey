import argparse
import sys
import warnings

from hey.version import VERSION

from .commands import chat, history


def main(prog: str | None = None) -> None:
    warnings.filterwarnings("ignore")

    parser = argparse.ArgumentParser(prog=prog, description="Hey is a CLI chat agent.")
    parser.add_argument("--version", action="version", version=f"%(prog)s {VERSION}")

    subparsers = parser.add_subparsers(dest="command")

    chat_parser = subparsers.add_parser("@chat", help="Start a chat session.")
    chat.add_arguments(chat_parser)

    history_parser = subparsers.add_parser("@history", help="Show chat history.")
    history.add_arguments(history_parser)

    raw_args = sys.argv[1:]
    if not raw_args:
        parser.print_help()
        raise SystemExit(1)

    first_arg = raw_args[0]
    if first_arg in ("-h", "--help"):
        pass
    elif not first_arg.startswith("@"):
        raw_args = ["@chat"] + raw_args

    args = parser.parse_args(raw_args)

    match args.command:
        case "@chat":
            chat.run(args)
        case "@history":
            history.run(args)
        case _:
            parser.print_help()
            raise SystemExit(1)
