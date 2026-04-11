import argparse

from hey.version import VERSION

from .commands.chat import run_chat


def build_parser(*, prog: str | None = None) -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog=prog, description="Hey is a workflow engine for Python.")
    parser.add_argument("--version", action="version", version=f"%(prog)s {VERSION}")
    return parser


def main(prog: str | None = None) -> None:
    parser = build_parser(prog=prog)
    parser.add_argument("prompt", nargs="+", help="The prompt to send to the LLM.")
    args = parser.parse_args()

    prompt = " ".join(args.prompt)
    run_chat(prompt=prompt)
