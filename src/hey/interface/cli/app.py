import argparse

from hey.version import VERSION

from .commands import chat, history


def main(prog: str | None = None) -> None:
    parser = argparse.ArgumentParser(prog=prog, description="Hey is a CLI chat agent.")
    parser.add_argument("--version", action="version", version=f"%(prog)s {VERSION}")
    parser.add_argument("prompt", nargs="*", help="The prompt to send to the LLM.")
    parser.add_argument("--history", action="store_true", help="Show chat history.")
    chat._add_options(parser)
    history.add_arguments(parser)

    args = parser.parse_args()

    if args.history:
        history.run(args)
    else:
        chat.run(args)
