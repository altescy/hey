import argparse

from hey.version import VERSION

from .commands import chat, show_chat_history


def build_parser(*, prog: str | None = None) -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog=prog, description="Hey is a workflow engine for Python.")
    parser.add_argument("--version", action="version", version=f"%(prog)s {VERSION}")
    parser.add_argument("prompt", nargs="*", help="The prompt to send to the LLM.")
    parser.add_argument("--show", choices=["chat-history"], help="Show additional information.")
    parser.add_argument("--temporary", action="store_true", help="Use temporary in-memory storage for chat history.")
    parser.add_argument(
        "--new-session", action="store_true", help="Start a new chat session instead of resuming the latest one."
    )
    return parser


def main(prog: str | None = None) -> None:
    parser = build_parser(prog=prog)
    args = parser.parse_args()

    if args.show == "chat-history":
        show_chat_history.run(args)
        return

    chat.run(args)
