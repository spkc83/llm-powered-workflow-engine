import re
from pathlib import Path

from workflow_engine.settings import Settings


ROOT = Path(__file__).parents[1]


def test_documentation_links_resolve():
    files = [ROOT / "README.md", ROOT / "CONTRIBUTING.md", *sorted((ROOT / "docs").glob("*.md"))]
    missing = []
    for path in files:
        for target in re.findall(r"\[[^\]]+\]\(([^)#]+)(?:#[^)]*)?\)", path.read_text()):
            if target.startswith(("http://", "https://", "mailto:", "#")):
                continue
            if not (path.parent / target).resolve().exists():
                missing.append((str(path.relative_to(ROOT)), target))
    assert missing == []


def test_env_example_keys_are_settings_or_ui_configuration():
    keys = set(re.findall(r"^#?\s*([A-Z][A-Z0-9_]+)=", (ROOT / ".env.example").read_text(), re.MULTILINE))
    settings_keys = {name.upper() for name in Settings.model_fields}
    assert keys - settings_keys <= {"BACKEND_URL", "BACKEND_AUTH_TOKEN"}


def test_required_deep_guides_exist():
    for name in ("current-state.md", "configuration.md", "ui.md", "testing.md"):
        assert (ROOT / "docs" / name).is_file()
