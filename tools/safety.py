"""
YouTube safety check before ClipBot posts anything on its own.
Goal: edgy and funny is fine — anything that could get ViceClips a strike, age-restricted or demonetized is not.
"""
import re

from tools.judge import MODELS, pick_models
import json
import os
import requests

# Never in a title/description (YouTube scans text too)
BANNED_WORDS = [
    "fuck", "shit", "bitch", "pussy", "dick", "cock", "cum", "nigg", "fag", "retard", "whore", "slut",
    "porn", "nude", "naked", "sex", "rape", "kill yourself", "kys",
]

RULES = """YouTube Community Guidelines + advertiser-friendly rules for a GTA 6 Shorts channel:
NOT OK (reject): nudity or sexual content/acts (incl. in-game strip clubs with visible nudity, sexual dialogue as the
focus), slurs or hate speech said by anyone (n-word, f-slur, etc.), harassment of a real person, real-life violence
or injuries, self-harm talk, minors in risky situations, dangerous real-world acts, doxxing / personal info,
drugs being used for real, scams, misleading clickbait, ANY gambling (real or in-game casino, slots, roulette,
blackjack, betting, sportsbooks, gambling sponsors like Stake on screen or mentioned).
CAUTION (allowed only if brief and not the focus): heavy swearing, in-game sexual jokes, in-game drug content.
OK: normal GTA violence, guns, crimes, robberies, in-game drug missions, crashes, police chases, rage/screaming,
banter, swearing in the audio, funny NPC moments, and naming the real streamer in the title (that's normal credit).
If the ONLY problem is swearing or a sketchy word in the TITLE, mark it safe and rewrite the title clean."""


GAMBLING = re.compile(r"\b(casino|slots?|stake\.com|roulette|blackjack|sportsbook|sportsbet\w*|gambl\w*)\b", re.I)
PREFIX = {"fuck", "shit", "nigg", "fag", "retard", "porn", "bitch"}   # match words starting with these
PATTERNS = [re.compile((r"\b" + re.escape(w) + r"\w*") if w in PREFIX else (r"\b" + re.escape(w) + r"s?\b"), re.I)
            for w in BANNED_WORDS]


def text_is_clean(text):
    return not any(p.search(text) for p in PATTERNS)


def safe_title(title):
    """Masks any banned word that slipped into a title (whole words only, so 'document' stays fine)."""
    out = title
    for p in PATTERNS:
        out = p.sub(lambda m: m.group(0)[0] + "*" * (len(m.group(0)) - 1), out)
    return out


def check(transcript, title, summary="", key=None):
    """Returns {"safe": bool, "reason": str, "title": safer title}."""
    key = key or os.environ.get("GEMINI_API_KEY", "")
    result = {"safe": True, "reason": "", "title": safe_title(title)}
    if not key:
        return result
    prompt = f"""{RULES}

Clip title: {title}
What happens: {summary}
Transcript (what's said):
{transcript[:5000]}

Would posting this to YouTube risk a strike, age-restriction or demonetization?
Reply ONLY with JSON: {{"safe": true/false, "reason": "short reason if unsafe",
 "title": "the title, rewritten ONLY if it has swear words or could be misleading (keep the vibe), else the same"}}"""
    body = {"contents": [{"parts": [{"text": prompt}]}],
            "generationConfig": {"responseMimeType": "application/json", "temperature": 0.1}}
    for model in sorted(pick_models(key, MODELS), key=lambda m: "lite" not in m):
        try:
            r = requests.post(f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent",
                              headers={"x-goog-api-key": key}, json=body, timeout=60)
        except requests.RequestException:
            continue
        if r.status_code == 200:
            try:
                v = json.loads(r.json()["candidates"][0]["content"]["parts"][0]["text"])
            except (KeyError, ValueError):
                continue
            result["safe"] = bool(v.get("safe", False))
            result["reason"] = v.get("reason", "")
            result["title"] = safe_title(v.get("title") or title)
            return result
    # couldn't reach the AI: only post if nothing obviously bad is said
    result["safe"] = text_is_clean(transcript) and text_is_clean(title) and not GAMBLING.search(title)
    result["reason"] = "" if result["safe"] else "swearing/slurs in the audio (AI check unavailable)"
    return result
