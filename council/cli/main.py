#!/usr/bin/env python3
"""
TheCouncil CLI — Typer-based command-line interface.

Commands:
  council run        Run a council debate (local or via API)
  council status     Poll the status of an API-backed run
  council artifact   Fetch and display the deliberation artifact for a run
  council personas   List, create, or delete saved personas via the API
  council export     Export a completed run artifact to JSON or Markdown

Usage:
  council run "Should we adopt microservices?"
  council run "Is zero-trust worth it?" --mode dynamic --agents 4
  council status <run_id>
  council artifact <run_id> --format markdown
  council personas list
  council personas create --name "CFO" --prompt "You are the CFO..."
  council export <run_id> --format markdown --out result.md
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import Optional

from dotenv import load_dotenv

load_dotenv()

import typer
from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

# Typer app
app = typer.Typer(
    name="council",
    help="TheCouncil — multi-agent AI deliberation engine",
    no_args_is_help=True,
    rich_markup_mode="rich",
)

personas_app = typer.Typer(help="Manage saved personas via the Council API.")
app.add_typer(personas_app, name="personas")

console = Console(highlight=False)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_ENV_API_URL = "COUNCIL_API_URL"
_ENV_API_TOKEN = "COUNCIL_API_TOKEN"


def _get_api_client():  # type: ignore[return]
    """Return a configured httpx.Client for the Council API."""
    import httpx  # type: ignore[import]

    base_url = os.getenv(_ENV_API_URL, "http://localhost:8000")
    token = os.getenv(_ENV_API_TOKEN, "")
    headers = {}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    return httpx.Client(base_url=base_url, headers=headers, timeout=600)


def _require_api_token() -> None:
    if not os.getenv(_ENV_API_TOKEN):
        console.print(
            Panel(
                f"[bold red]{_ENV_API_TOKEN} is not set.[/]\n"
                "Export it or add it to your .env file:\n"
                f"  [dim]export {_ENV_API_TOKEN}=your-token-here[/]",
                title="Missing API token",
                border_style="red",
            )
        )
        raise typer.Exit(1)


# ---------------------------------------------------------------------------
# council run
# ---------------------------------------------------------------------------


@app.command("run")
def cmd_run(
    question: str = typer.Argument(..., help="The debate question or topic."),
    mode: Optional[str] = typer.Option(
        None, "--mode", "-m", help="Personality mode: canned | dynamic | hybrid | generated"
    ),
    agents: Optional[int] = typer.Option(None, "--agents", "-n", help="Number of agents."),
    rounds: Optional[int] = typer.Option(None, "--rounds", "-r", help="Number of debate rounds."),
    config_file: Optional[Path] = typer.Option(
        None, "--config", "-c", help="Path to an agents.yaml config file."
    ),
    no_guardrails: bool = typer.Option(False, "--no-guardrails", help="Disable content guardrails."),
    api: bool = typer.Option(
        False, "--api", help="Submit run to the Council API instead of running locally."
    ),
    wait: bool = typer.Option(True, "--wait/--no-wait", help="When using --api, poll until done."),
    output_file: Optional[Path] = typer.Option(
        None, "--out", "-o", help="Write result JSON to this file."
    ),
) -> None:
    """Run a council debate on QUESTION.

    By default runs locally. Use [bold]--api[/] to submit to the Council API
    (requires [bold]COUNCIL_API_TOKEN[/] and optionally [bold]COUNCIL_API_URL[/]).
    """
    if api:
        _run_via_api(question, mode, agents, rounds, wait, output_file)
    else:
        _run_local(question, mode, agents, rounds, config_file, no_guardrails, output_file)


def _run_local(
    question: str,
    mode: Optional[str],
    agents: Optional[int],
    rounds: Optional[int],
    config_file: Optional[Path],
    no_guardrails: bool,
    output_file: Optional[Path],
) -> None:
    """Run the debate engine locally (imports council.core.council)."""
    from council.core.council import main as council_main

    argv = [question]
    if mode:
        argv += ["--mode", mode]
    if agents:
        argv += ["--agents", str(agents)]
    if config_file:
        argv += ["--config", str(config_file)]
    if no_guardrails:
        argv += ["--no-guardrails"]

    # Override sys.argv so the argparse-based main() picks it up
    original_argv = sys.argv[:]
    sys.argv = ["council"] + argv
    try:
        council_main()
    finally:
        sys.argv = original_argv


def _run_via_api(
    question: str,
    mode: Optional[str],
    agents: Optional[int],
    rounds: Optional[int],
    wait: bool,
    output_file: Optional[Path],
) -> None:
    """Submit the debate to the Council API and optionally poll until done."""
    _require_api_token()
    import httpx  # type: ignore[import]

    config: dict = {}
    if mode:
        config["mode"] = mode
    if agents:
        config["num_agents"] = agents
    if rounds:
        config["num_rounds"] = rounds

    with _get_api_client() as client:
        try:
            resp = client.post("/runs", json={"question": question, "config": config})
            resp.raise_for_status()
        except httpx.HTTPError as exc:
            console.print(f"[red]API error:[/] {exc}")
            raise typer.Exit(1)

        run = resp.json()
        run_id = run["run_id"]
        console.print(f"[green]Run created:[/] {run_id}")
        console.print(f"Status: {run['status']}")

        if not wait:
            if output_file:
                output_file.write_text(json.dumps(run, indent=2))
            return

        console.print("[dim]Polling for completion…[/]")
        import time

        while True:
            time.sleep(3)
            try:
                resp = client.get(f"/runs/{run_id}")
                resp.raise_for_status()
            except httpx.HTTPError as exc:
                console.print(f"[yellow]Poll error:[/] {exc}")
                continue

            run = resp.json()
            status_val = run.get("status", "")
            console.print(f"  status={status_val}")

            if status_val in ("completed", "failed"):
                break

        if run.get("status") == "completed":
            console.print(f"[bold green]✓ Run completed[/] — run_id={run_id}")
        else:
            error = run.get("error", "Unknown error")
            console.print(f"[bold red]✗ Run failed:[/] {error}")

        if output_file:
            output_file.write_text(json.dumps(run, indent=2))
            console.print(f"Result written to {output_file}")


# ---------------------------------------------------------------------------
# council status
# ---------------------------------------------------------------------------


@app.command("status")
def cmd_status(
    run_id: str = typer.Argument(..., help="The run ID to check."),
) -> None:
    """Poll the status of a council run submitted via the API."""
    _require_api_token()
    import httpx  # type: ignore[import]

    with _get_api_client() as client:
        try:
            resp = client.get(f"/runs/{run_id}")
            resp.raise_for_status()
        except httpx.HTTPError as exc:
            console.print(f"[red]API error:[/] {exc}")
            raise typer.Exit(1)

        run = resp.json()

    _print_run_table(run)


def _print_run_table(run: dict) -> None:
    table = Table(title=f"Run {run.get('run_id', '?')}", show_header=True)
    table.add_column("Field")
    table.add_column("Value")
    for field in ("run_id", "status", "question", "created_at", "started_at", "finished_at"):
        val = run.get(field)
        if val is not None:
            table.add_row(field, str(val))
    if run.get("error"):
        table.add_row("error", Text(run["error"], style="red"))
    console.print(table)


# ---------------------------------------------------------------------------
# council artifact
# ---------------------------------------------------------------------------


@app.command("artifact")
def cmd_artifact(
    run_id: str = typer.Argument(..., help="The run ID to fetch the artifact for."),
    format: str = typer.Option("json", "--format", "-f", help="Output format: json | markdown"),
    out: Optional[Path] = typer.Option(None, "--out", "-o", help="Write artifact to this file."),
) -> None:
    """Fetch and display the structured deliberation artifact for a completed run."""
    _require_api_token()
    import httpx  # type: ignore[import]

    # Try dedicated artifact endpoint first, fall back to run result
    with _get_api_client() as client:
        try:
            resp = client.get(f"/runs/{run_id}/artifact", params={"format": format})
            if resp.status_code == 404:
                # Endpoint not yet available on older deployments — build from run result
                resp = client.get(f"/runs/{run_id}")
                resp.raise_for_status()
                run = resp.json()
                artifact_content = json.dumps(run.get("result") or {}, indent=2)
            else:
                resp.raise_for_status()
                data = resp.json()
                artifact_content = (
                    data.get("artifact") if format == "markdown" else json.dumps(data.get("artifact"), indent=2)
                )
        except httpx.HTTPError as exc:
            console.print(f"[red]API error:[/] {exc}")
            raise typer.Exit(1)

    if out:
        out.write_text(str(artifact_content))
        console.print(f"[green]Artifact written to[/] {out}")
    else:
        console.print(artifact_content)


# ---------------------------------------------------------------------------
# council export
# ---------------------------------------------------------------------------


@app.command("export")
def cmd_export(
    run_id: str = typer.Argument(..., help="Run ID to export."),
    format: str = typer.Option("json", "--format", "-f", help="Export format: json | markdown"),
    out: Optional[Path] = typer.Option(None, "--out", "-o", help="Output file (default: stdout)."),
) -> None:
    """Export a completed run's artifact to JSON or Markdown.

    This is a convenience alias for [bold]council artifact[/] with explicit file output.
    """
    cmd_artifact(run_id=run_id, format=format, out=out)


# ---------------------------------------------------------------------------
# council personas
# ---------------------------------------------------------------------------


@personas_app.command("list")
def personas_list() -> None:
    """List saved personas for the authenticated user."""
    _require_api_token()
    import httpx  # type: ignore[import]

    with _get_api_client() as client:
        try:
            resp = client.get("/me/personas")
            resp.raise_for_status()
        except httpx.HTTPError as exc:
            console.print(f"[red]API error:[/] {exc}")
            raise typer.Exit(1)

    personas = resp.json()
    if not personas:
        console.print("[dim]No saved personas.[/]")
        return

    table = Table(title="Saved Personas", show_header=True)
    table.add_column("ID")
    table.add_column("Name")
    table.add_column("Mode")
    table.add_column("Created")
    for p in personas:
        table.add_row(
            p.get("persona_id", "?"),
            p.get("name", ""),
            p.get("mode", ""),
            str(p.get("created_at", "")),
        )
    console.print(table)


@personas_app.command("create")
def personas_create(
    name: str = typer.Option(..., "--name", "-n", help="Persona name."),
    prompt: str = typer.Option(..., "--prompt", "-p", help="System prompt for the persona."),
    mode: str = typer.Option("custom", "--mode", "-m", help="Persona mode: canned | mbti | custom"),
    description: Optional[str] = typer.Option(None, "--desc", help="Short description."),
) -> None:
    """Create a new saved persona via the Council API."""
    _require_api_token()
    import httpx  # type: ignore[import]

    with _get_api_client() as client:
        try:
            resp = client.post(
                "/me/personas",
                json={
                    "name": name,
                    "mode": mode,
                    "system_prompt": prompt,
                    "description": description,
                },
            )
            resp.raise_for_status()
        except httpx.HTTPError as exc:
            console.print(f"[red]API error:[/] {exc}")
            raise typer.Exit(1)

    p = resp.json()
    console.print(f"[green]Persona created:[/] {p.get('persona_id')} — {p.get('name')}")


@personas_app.command("delete")
def personas_delete(
    persona_id: str = typer.Argument(..., help="Persona ID to delete."),
) -> None:
    """Delete a saved persona."""
    _require_api_token()
    import httpx  # type: ignore[import]

    with _get_api_client() as client:
        try:
            resp = client.delete(f"/me/personas/{persona_id}")
            resp.raise_for_status()
        except httpx.HTTPError as exc:
            console.print(f"[red]API error:[/] {exc}")
            raise typer.Exit(1)

    console.print(f"[green]Persona {persona_id} deleted.[/]")


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------


def main() -> None:
    """CLI entry point (referenced in pyproject.toml [project.scripts])."""
    app()


if __name__ == "__main__":
    main()

