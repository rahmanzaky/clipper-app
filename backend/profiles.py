"""Campaign profile storage — save/reuse topic/hashtag/duration rules per campaign
instead of re-typing CLI flags every run. Stored in ../campaigns.json.
"""
import json
import os

_PROFILES_PATH = os.path.join(os.path.dirname(__file__), "..", "campaigns.json")


def list_profiles() -> dict:
    """Return all saved profiles, keyed by name — used to populate a UI dropdown."""
    if not os.path.exists(_PROFILES_PATH):
        return {}
    with open(_PROFILES_PATH) as f:
        return json.load(f)


def load_profile(name: str) -> dict:
    if not os.path.exists(_PROFILES_PATH):
        raise FileNotFoundError(f"No campaigns.json found — no profiles saved yet")
    with open(_PROFILES_PATH) as f:
        profiles = json.load(f)
    if name not in profiles:
        available = ", ".join(profiles.keys()) or "(none)"
        raise KeyError(f"No profile named '{name}'. Available: {available}")
    return profiles[name]


def save_profile(name: str, topics: list, min_duration: float, max_duration: float, hashtag: str) -> None:
    profiles = {}
    if os.path.exists(_PROFILES_PATH):
        with open(_PROFILES_PATH) as f:
            profiles = json.load(f)
    profiles[name] = {
        "topics": topics,
        "min_duration": min_duration,
        "max_duration": max_duration,
        "hashtag": hashtag,
    }
    with open(_PROFILES_PATH, "w") as f:
        json.dump(profiles, f, indent=2)
