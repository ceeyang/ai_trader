"""Command-line entrypoint for ai_trader."""

import typer

from ai_trader import __version__

app = typer.Typer(no_args_is_help=True)


@app.callback()
def main() -> None:
    """ai_trader command-line interface."""


@app.command()
def version() -> None:
    """Print the installed ai_trader version."""
    print(__version__)
