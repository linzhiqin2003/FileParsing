"""CLI interface — Typer + Rich with strategy-aware parsing."""

from __future__ import annotations

import asyncio
from pathlib import Path

import typer
from rich.console import Console
from rich.panel import Panel
from rich.progress import (
    BarColumn,
    MofNCompleteColumn,
    Progress,
    SpinnerColumn,
    TextColumn,
    TimeElapsedColumn,
)
from rich.table import Table
from rich.text import Text

from file_parse_engine import __version__
from file_parse_engine.config import ParseStrategy, get_settings
from file_parse_engine.engine import FileParseEngine
from file_parse_engine.parsers import supported_extensions
from file_parse_engine.utils.logger import setup_logging

app = typer.Typer(
    name="fpe",
    help="FileParseEngine — multi-format file parser for RAG pipelines",
    no_args_is_help=True,
    rich_markup_mode="rich",
)
console = Console()

# ------------------------------------------------------------------
# Strategy display helpers
# ------------------------------------------------------------------

_STRATEGY_STYLE = {
    "fast": ("FAST", "green", "FREE"),
    "ocr": ("OCR", "blue", "FREE"),
    "hybrid": ("HYBRID", "yellow", "LOW"),
    "vlm": ("VLM", "red", "HIGH"),
}


def _strategy_badge(strategy: str) -> Text:
    label, color, _ = _STRATEGY_STYLE.get(strategy, ("?", "white", "?"))
    return Text(f" {label} ", style=f"bold white on {color}")


def _cost_badge(strategy: str) -> Text:
    _, _, cost = _STRATEGY_STYLE.get(strategy, ("?", "white", "?"))
    style_map = {"FREE": "bold green", "LOW": "bold yellow", "HIGH": "bold red"}
    return Text(cost, style=style_map.get(cost, ""))


def _fmt_tokens(n: int) -> str:
    """Format token count: 1234 → '1,234', 1234567 → '1.23M'."""
    if n >= 1_000_000:
        return f"{n / 1_000_000:.2f}M"
    return f"{n:,}"


# ------------------------------------------------------------------
# Callbacks
# ------------------------------------------------------------------

def _version_callback(value: bool) -> None:
    if value:
        console.print(f"[bold cyan]FileParseEngine[/] v{__version__}")
        raise typer.Exit()


@app.callback()
def main(
    version: bool = typer.Option(
        False, "--version", "-V",
        callback=_version_callback, is_eager=True,
    ),
) -> None:
    """FileParseEngine — multi-format file parser for RAG pipelines."""


# ------------------------------------------------------------------
# parse command
# ------------------------------------------------------------------

@app.command()
def parse(
    source: Path = typer.Argument(..., help="File or directory to parse", exists=True),
    output: Path = typer.Option("output", "--output", "-o", help="Output directory"),
    strategy: str = typer.Option("", "--strategy", "-s", help="Parse strategy: fast (default) | ocr | hybrid | vlm"),
    recursive: bool = typer.Option(False, "--recursive", "-r", help="Recurse into subdirectories"),
    model: str = typer.Option("", "--model", "-m", help="VLM model alias from routes (e.g. qwen3.5-9b, gemini-flash)"),
    enrich_links: bool = typer.Option(False, "--enrich-links", "-l", help="Inject real PDF hyperlinks into output"),
    extract_images: bool = typer.Option(False, "--extract-images", "-i", help="Export embedded images & inject into Markdown"),
    page_tags: bool = typer.Option(False, "--page-tags", "-p", help="Insert <!-- page:N --> comments for source tracing"),
    force: bool = typer.Option(False, "--force", "-f", help="Re-parse files even if output already exists"),
    concurrency: int = typer.Option(0, "--concurrency", "-c", help="Max concurrent VLM requests (0 = auto)"),
    verbose: bool = typer.Option(False, "--verbose", "-v", help="Enable debug logging"),
) -> None:
    """Parse file(s) and output Markdown."""
    setup_logging(verbose=verbose)
    settings = get_settings()

    # Apply CLI overrides
    if strategy:
        settings.strategy = strategy  # type: ignore[assignment]
    if concurrency > 0:
        settings.vlm_concurrency = concurrency
    if model:
        settings.vlm_model_override = model  # type: ignore[attr-defined]
    if enrich_links:
        settings.enrich_links = True
    if extract_images:
        settings.extract_images = True
    if page_tags:
        settings.page_tags = True

    effective_strategy: ParseStrategy = settings.strategy

    engine = FileParseEngine(settings)

    # Collect files
    if source.is_file():
        files = [source]
    else:
        files = engine.collect_files(source, recursive=recursive)

    if not files:
        console.print("[yellow]No supported files found.[/]")
        raise typer.Exit(1)

    # Checkpoint: skip files whose output already exists
    skipped: list[Path] = []
    if not force:
        todo: list[Path] = []
        for f in files:
            out_file = output / f"{f.stem}.md"
            if out_file.exists():
                skipped.append(f)
            else:
                todo.append(f)
        files = todo

    if not files and skipped:
        console.print(f"[green]All {len(skipped)} file(s) already parsed. Use --force to re-parse.[/]")
        raise typer.Exit(0)

    # Header panel
    badge = _strategy_badge(effective_strategy)
    cost = _cost_badge(effective_strategy)

    # Resolve model name for display
    model_display = ""
    if effective_strategy in ("vlm", "hybrid"):
        try:
            from file_parse_engine.vlm.routes import load_routes
            rc = load_routes(settings.vlm_routes_file)
            model_name = settings.vlm_model_override or rc.primary
            m = rc.models.get(model_name)
            model_display = m.model_id if m else model_name
        except Exception:
            model_display = settings.vlm_model_override or "auto"

    # Enrichment flags
    flags = []
    if enrich_links:
        flags.append("links")
    if extract_images:
        flags.append("images")
    if page_tags:
        flags.append("page-tags")

    header = Text()
    header.append("  Strategy  ", style="dim")
    header.append_text(badge)
    header.append("   Cost  ", style="dim")
    header.append_text(cost)
    if model_display:
        header.append("   Model  ", style="dim")
        header.append(model_display, style="cyan")
    header.append("\n")
    header.append(f"  Files     ", style="dim")
    header.append(f"{len(files)}", style="bold")
    if skipped:
        header.append(f" [dim]({len(skipped)} skipped)[/]")
    header.append(f"          Output  ", style="dim")
    header.append(str(output), style="cyan")
    if flags:
        header.append(f"   Enrich  ", style="dim")
        header.append(", ".join(flags), style="yellow")

    console.print()
    console.print(Panel(
        header,
        title=f"[bold cyan]FileParseEngine[/] [dim]v{__version__}[/]",
        border_style="cyan",
        padding=(0, 1),
    ))
    console.print()

    # Parse
    import time
    t0 = time.perf_counter()
    results = asyncio.run(_parse_files(engine, files, output, verbose, effective_strategy, settings.page_tags))
    elapsed = time.perf_counter() - t0

    # Summary table
    success = sum(1 for r in results if r is not None)
    failed = len(files) - success

    table = Table(border_style="dim", show_header=True, header_style="bold")
    table.add_column("File", style="cyan", max_width=40)
    table.add_column("Pages", justify="right", style="bold")
    table.add_column("Strategy", justify="center")
    table.add_column("Provider", style="dim")
    table.add_column("Output", style="green", max_width=40)
    table.add_column("Status", justify="center")

    for file, result in zip(files, results):
        if result is not None:
            providers = {p.provider for p in result.pages if p.provider}
            prov_str = ", ".join(sorted(providers)) if providers else "-"
            strat_label, strat_color, _ = _STRATEGY_STYLE.get(effective_strategy, ("?", "white", "?"))
            table.add_row(
                file.name,
                str(result.page_count),
                Text(strat_label, style=strat_color),
                prov_str,
                str(result.metadata.get("output_file", "")),
                Text(" OK ", style="bold white on green"),
            )
        else:
            table.add_row(
                file.name, "-", "-", "-", "-",
                Text(" FAIL ", style="bold white on red"),
            )

    console.print(table)
    console.print()

    # Final tally
    parts = []
    if success:
        parts.append(f"[bold green]{success}[/] succeeded")
    if failed:
        parts.append(f"[bold red]{failed}[/] failed")
    parts.append(f"[dim]{elapsed:.1f}s[/]")
    console.print("  " + "  ·  ".join(parts))

    # VLM cost summary (only shown when VLM was actually used)
    in_tok, out_tok = engine.vlm_total_tokens
    if in_tok or out_tok:
        total_cost = engine.vlm_total_cost
        reqs = engine.vlm_request_count

        cost_text = Text()
        cost_text.append("  VLM  ", style="bold dim")
        cost_text.append(f"{reqs} request(s)", style="dim")
        cost_text.append("  ·  ", style="dim")
        cost_text.append(f"{_fmt_tokens(in_tok)} in", style="cyan")
        cost_text.append(" + ", style="dim")
        cost_text.append(f"{_fmt_tokens(out_tok)} out", style="cyan")
        cost_text.append("  ·  ", style="dim")
        if total_cost < 0.001:
            cost_text.append(f"${total_cost:.6f}", style="bold green")
        elif total_cost < 0.1:
            cost_text.append(f"${total_cost:.4f}", style="bold yellow")
        else:
            cost_text.append(f"${total_cost:.2f}", style="bold red")

        console.print(cost_text)

    console.print()


async def _parse_files(
    engine: FileParseEngine,
    files: list[Path],
    output: Path,
    verbose: bool,
    strategy: str,
    page_tags: bool = False,
) -> list:
    """Parse files with a Rich progress bar."""
    results = []

    with Progress(
        SpinnerColumn("dots"),
        TextColumn("[bold]{task.description}"),
        BarColumn(bar_width=30, complete_style="cyan", finished_style="green"),
        MofNCompleteColumn(),
        TextColumn("[dim]·[/]"),
        TimeElapsedColumn(),
        console=console,
        transient=True,
    ) as progress:
        task = progress.add_task("Parsing", total=len(files))

        for file in files:
            progress.update(task, description=f"[cyan]{file.name}[/]")

            # Page-level progress callback for OCR/VLM strategies
            page_task_id = None

            def _on_page(page_num: int, total: int) -> None:
                nonlocal page_task_id
                if page_task_id is None:
                    page_task_id = progress.add_task(
                        f"  [dim]page 0/{total}[/]", total=total,
                    )
                if page_num == 0:
                    return  # just init, don't advance
                progress.update(
                    page_task_id,
                    completed=page_num,
                    description=f"  [dim]page {page_num}/{total}[/]",
                )

            try:
                doc = await engine.parse(file, on_page=_on_page)
                output_file = doc.save(output, page_tags=page_tags)
                doc.metadata["output_file"] = str(output_file)
                results.append(doc)
            except Exception as exc:
                if verbose:
                    console.print_exception()
                else:
                    console.print(f"  [red]✗[/] {file.name} — {exc}")
                results.append(None)

            # Clean up page-level task
            if page_task_id is not None:
                progress.remove_task(page_task_id)
                page_task_id = None

            progress.advance(task)

    return results


# ------------------------------------------------------------------
# formats command
# ------------------------------------------------------------------

@app.command()
def formats() -> None:
    """List all supported file formats."""
    exts = supported_extensions()

    categories = {
        "pdf": "Document",
        "docx": "Document (Office)", "pptx": "Presentation",
        "xlsx": "Spreadsheet", "xls": "Spreadsheet",
        "csv": "Spreadsheet", "tsv": "Spreadsheet",
        "png": "Image", "jpg": "Image", "jpeg": "Image",
        "tiff": "Image", "tif": "Image", "bmp": "Image", "webp": "Image",
        "html": "Web", "htm": "Web", "xhtml": "Web", "xml": "Web",
        "txt": "Text", "text": "Text", "md": "Text", "markdown": "Text", "rst": "Text",
        "epub": "eBook", "rtf": "Rich Text",
    }

    table = Table(title="Supported Formats", border_style="cyan", show_lines=False)
    table.add_column("Extension", style="bold cyan")
    table.add_column("Category")
    table.add_column("VLM Required", justify="center")

    vlm_types = {"pdf", "png", "jpg", "jpeg", "tiff", "tif", "bmp", "webp"}

    for ext in exts:
        vlm_req = Text("optional", style="yellow") if ext in vlm_types else Text("no", style="green")
        table.add_row(f".{ext}", categories.get(ext, "Other"), vlm_req)

    console.print()
    console.print(table)
    console.print()


# ------------------------------------------------------------------
# config command
# ------------------------------------------------------------------

@app.command()
def config() -> None:
    """Show current configuration."""
    settings = get_settings()

    strat_label, strat_color, cost_label = _STRATEGY_STYLE.get(
        settings.strategy, ("?", "white", "?"),
    )

    table = Table(title="Configuration", border_style="cyan")
    table.add_column("Setting", style="bold")
    table.add_column("Value")

    # Strategy
    table.add_row("Strategy", Text(f"{strat_label} (cost: {cost_label})", style=strat_color))

    # VLM info
    table.add_row("VLM Routes", settings.vlm_routes_file or "[dim]auto-detect[/]")
    table.add_row("Concurrency", str(settings.vlm_concurrency))
    table.add_row("Timeout", f"{settings.vlm_timeout}s")

    # API keys — masked
    table.add_row(
        "OpenRouter Key",
        "***" + settings.openrouter_api_key[-4:]
        if settings.openrouter_api_key else Text("Not set", style="red"),
    )
    table.add_row(
        "SiliconFlow Key",
        "***" + settings.siliconflow_api_key[-4:]
        if settings.siliconflow_api_key else Text("Not set", style="red"),
    )

    # OCR
    from file_parse_engine.ocr import ocr_available
    ocr_status = Text(" OK ", style="bold white on green") if ocr_available() else Text(" Not installed ", style="bold white on red")
    table.add_row("RapidOCR", ocr_status)

    # Image
    table.add_row("Image DPI", str(settings.image_dpi))
    table.add_row("Image Max Size", f"{settings.image_max_size}px")
    table.add_row("Output Dir", settings.output_dir)

    console.print()
    console.print(table)
    console.print()


# ------------------------------------------------------------------
# routes command (new)
# ------------------------------------------------------------------

@app.command()
def routes() -> None:
    """Show current VLM routing configuration."""
    from file_parse_engine.vlm.routes import load_routes

    settings = get_settings()

    try:
        rc = load_routes(settings.vlm_routes_file)
    except FileNotFoundError as exc:
        console.print(f"[red]{exc}[/]")
        raise typer.Exit(1)

    # Providers
    prov_table = Table(title="VLM Providers", border_style="cyan")
    prov_table.add_column("Name", style="bold cyan")
    prov_table.add_column("Base URL")
    prov_table.add_column("Key Env")
    prov_table.add_column("Status", justify="center")

    for p in rc.providers.values():
        status = Text(" OK ", style="bold white on green") if p.is_configured else Text(" MISSING ", style="bold white on red")
        table_url = p.base_url if len(p.base_url) < 50 else p.base_url[:47] + "..."
        prov_table.add_row(p.name, table_url, p.api_key_env, status)

    console.print()
    console.print(prov_table)

    # Models
    model_table = Table(title="Models", border_style="cyan")
    model_table.add_column("Alias", style="bold")
    model_table.add_column("Provider")
    model_table.add_column("Model ID", style="cyan")
    model_table.add_column("Tokens", justify="right")
    model_table.add_column("$/M in", justify="right")
    model_table.add_column("$/M out", justify="right")

    for m in rc.models.values():
        in_p = f"${m.input_price:.2f}" if m.input_price else Text("free", style="green")
        out_p = f"${m.output_price:.2f}" if m.output_price else Text("free", style="green")
        model_table.add_row(m.name, m.provider, m.model_id, str(m.max_tokens), in_p, out_p)

    console.print(model_table)

    # Routes
    route_table = Table(title="Task Routing", border_style="cyan")
    route_table.add_column("Task", style="bold")
    route_table.add_column("Model", style="cyan")

    for task, model_name in rc.routes.items():
        route_table.add_row(task, model_name)

    console.print(route_table)

    # Defaults
    console.print(f"\n  [bold]Primary:[/] {rc.primary}  ·  [bold]Fallback:[/] {rc.fallback or '[dim]none[/]'}")
    console.print(f"  [bold]Concurrency:[/] {rc.concurrency}  ·  [bold]Timeout:[/] {rc.timeout}s")
    console.print()
