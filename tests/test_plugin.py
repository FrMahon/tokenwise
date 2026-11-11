import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def load(rel):
    return json.loads((ROOT / rel).read_text(encoding="utf-8"))


def test_plugin_manifest_and_marketplace_agree():
    plugin = load(".claude-plugin/plugin.json")
    market = load(".claude-plugin/marketplace.json")
    assert plugin["name"] == "tokenwise"
    assert market["owner"]["name"] and [p["name"] for p in market["plugins"]] == [plugin["name"]]
    assert market["plugins"][0]["source"] == "."


def test_skill_has_frontmatter_and_never_installs_silently():
    text = (ROOT / "skills" / "report" / "SKILL.md").read_text(encoding="utf-8")
    assert text.startswith("---\n")
    head = text.split("---")[1]
    assert "name: report" in head and "description:" in head
    assert "allowed-tools: Bash(tokenwise *)" in head  # pre-approves only the tokenwise CLI, not pipx/uv
    assert "do NOT install" in text
