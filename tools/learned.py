"""Loads learned.json (written by tools/learn.py) so the bot can use what it learned."""
import json
import random

try:
    with open("learned.json") as f:
        LEARNED = json.load(f)
except (OSError, ValueError):
    LEARNED = {}


def weighted_choice(options, weights_key):
    """Pick an option, favouring ones you rated 👍 (still tries others sometimes)."""
    w = LEARNED.get(weights_key, {})
    options = list(options)
    weights = [w.get(str(o), 1.0) for o in options]
    if sum(weights) <= 0:
        weights = [1.0] * len(options)
    return random.choices(options, weights=weights)[0]


def streamer_weight(name):
    return LEARNED.get("streamer_weight", {}).get(name.lower(), 1.0)


def spike_mult(name):
    return LEARNED.get("spike_mult", {}).get(name.lower(), 1.0)
