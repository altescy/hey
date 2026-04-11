import argparse

from hey.version import VERSION

from .commands import chat, show_chat_history


def build_parser(*, prog: str | None = None) -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog=prog, description="Hey is a workflow engine for Python.")
    parser.add_argument("--version", action="version", version=f"%(prog)s {VERSION}")
    return parser


def main(prog: str | None = None) -> None:
    parser = build_parser(prog=prog)
    parser.add_argument("prompt", nargs="*", help="The prompt to send to the LLM.")
    parser.add_argument("--show", choices=["chat-history"], help="Show additional information.")
    args = parser.parse_args()

    if args.show == "chat-history":
        show_chat_history.run(args)
        return

    chat.run(args)
