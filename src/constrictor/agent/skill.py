from __future__ import annotations

from importlib import resources
from pathlib import Path

from jinja2 import Environment, FileSystemLoader, select_autoescape

from constrictor import __version__


def _template_dir() -> Path:
    """Return the absolute path to the agent templates directory."""
    return Path(__file__).parent / "templates"


def generate_skill_md(
    output_path: Path | None = None,
    project_name: str = "constrictor",
) -> str:
    """Render the SKILL.md Jinja2 template and return the result as a string.

    If *output_path* is given, the rendered content is also written to that file.
    """
    template_dir = _template_dir()
    env = Environment(
        loader=FileSystemLoader(str(template_dir)),
        autoescape=select_autoescape(disabled_extensions=("jinja", "md.jinja")),
        keep_trailing_newline=True,
    )
    template = env.get_template("SKILL.md.jinja")
    rendered = template.render(
        version=__version__,
        project_name=project_name,
    )

    if output_path is not None:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(rendered, encoding="utf-8")

    return rendered
