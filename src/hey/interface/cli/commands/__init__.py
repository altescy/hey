import argparse
from typing import Protocol, runtime_checkable


@runtime_checkable
class Command(Protocol):
    @staticmethod
    def add_arguments(parser: argparse.ArgumentParser) -> None: ...

    @staticmethod
    def run(args: argparse.Namespace) -> None: ...
