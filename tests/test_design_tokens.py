from pathlib import Path

CSS = Path("src/library/web/static/app.css").read_text()


def test_component_classes_are_compiled():
    for name in (".panel", ".section", ".eyebrow", ".title", ".meta",
                 ".btn-primary", ".btn-secondary", ".badge"):
        assert name in CSS, f"{name} missing from compiled app.css"


def test_accent_soft_token_is_compiled():
    # A colon after the name distinguishes a real definition from the existing
    # var(--color-accent-soft, ...) fallback reference in .cover-dropzone.is-dragover,
    # which already contains the bare string without defining the variable.
    assert "--color-accent-soft:" in CSS
