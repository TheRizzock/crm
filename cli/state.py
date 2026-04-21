"""
Persists session state (active file, etc.) to .cli_state.json at project root.
"""

import json
import os

STATE_FILE = os.path.abspath(os.path.join(os.path.dirname(__file__), "../.cli_state.json"))


def load() -> dict:
    if not os.path.exists(STATE_FILE):
        return {}
    with open(STATE_FILE) as f:
        return json.load(f)


def save(state: dict) -> None:
    with open(STATE_FILE, "w") as f:
        json.dump(state, f, indent=2)


def get_active_file() -> str | None:
    return load().get("active_file")


def set_active_file(path: str) -> None:
    state = load()
    state["active_file"] = path
    save(state)
