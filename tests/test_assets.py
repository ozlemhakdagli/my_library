import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
STATIC = ROOT / "src" / "library" / "web" / "static"
TEMPLATES = ROOT / "src" / "library" / "web" / "templates"


def test_htmx_is_vendored_and_non_empty():
    htmx = STATIC / "htmx.min.js"
    assert htmx.is_file()
    assert htmx.stat().st_size > 0


def test_app_css_is_built_with_required_classes():
    css_path = STATIC / "app.css"
    assert css_path.is_file()
    css = css_path.read_text(encoding="utf-8")
    assert ".grid" in css
    assert "rounded-xl" in css


def test_templates_do_not_reference_external_assets():
    tag_pattern = re.compile(r"<(script|link)\b[^>]*>", re.IGNORECASE)
    offenders = []
    for template in TEMPLATES.rglob("*.html"):
        for match in tag_pattern.finditer(template.read_text(encoding="utf-8")):
            if re.search(r"""(src|href)\s*=\s*["']?(https?:)?//""", match.group(0), re.IGNORECASE):
                offenders.append(f"{template.relative_to(ROOT)}: {match.group(0)}")
    assert offenders == []
