"""Turns a Twitch clip into a YouTube Shorts title, description and tags."""
import random
import re

# Nicknames viewers actually search for. Add more anytime.
NICKNAMES = {
    "ishowspeed": "Speed",
    "kaicenat": "Kai Cenat",
    "xqc": "xQc",
    "lacy": "Lacy",
    "jynxzi": "Jynxzi",
    "caseoh_": "CaseOh",
    "adinross": "Adin Ross",
    "summit1g": "Summit1g",
    "ohnepixel": "ohnePixel",
}

# Used when the Twitch title is too short or vague ("wtf", "LMAO", ...)
HOOKS = [
    "{name} was NOT ready for this in GTA 6 💀",
    "{name} can't believe what just happened in GTA 6 😭",
    "GTA 6 did {name} dirty 💀",
    "{name} lost it in GTA 6 😂",
    "This GTA 6 moment broke {name} 💀",
    "{name} found something crazy in GTA 6 👀",
    "Nobody expected this from {name} in GTA 6 😳",
]

# YouTube shows the first 3 hashtags above the title, and ignores ALL of them if there are more than 15.
# So: 3 strong ones first, then streamer + what happens, ~8 total.
HASHTAGS = ["#gta6", "#gtavi", "#shorts"]
EXTRA_HASHTAGS = ["#gta6funnymoments", "#gaming"]
MAX_TITLE = 90  # YouTube allows 100; keep a little room


def streamer_name(clip):
    login = clip["broadcaster_name"].lower()
    return NICKNAMES.get(login, clip["broadcaster_name"])


def clean(text):
    text = re.sub(r"[^\w\s'?!.,&:$-]", " ", text)   # drop emojis/symbols
    text = re.sub(r"![\w]+", " ", text)              # drop !commands
    text = re.sub(r"@\w+", " ", text)                # drop @mentions
    text = re.sub(r"\s*[|/]\s*", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def make_title(clip):
    name = streamer_name(clip)
    title = clean(clip["title"])

    # Vague title -> use a hook instead
    if len(title.split()) < 3:
        title = random.choice(HOOKS).format(name=name)
    else:
        # Make sure the streamer and the game are in the title (people search for them)
        if name.lower() not in title.lower():
            title = f"{name}: {title}"
        if "gta" not in title.lower():
            title += " in GTA 6"
        if not re.search(r"[💀😭😂😳👀🔥]$", title):
            title += " " + random.choice(["💀", "😭", "😂", "🔥"])

    if not any(title.startswith(n) for n in NICKNAMES.values()):
        title = title[0].upper() + title[1:]
    if len(title) > MAX_TITLE:
        title = title[: MAX_TITLE - 3].rsplit(" ", 1)[0] + "..."
    return title


def make_description(clip, title, content_tags=()):
    name = streamer_name(clip)
    login = clip["broadcaster_name"].lower()
    site = "youtube.com/@" + login if "youtube" in clip.get("url", "") else f"twitch.tv/{login}"
    tags = HASHTAGS + ["#" + re.sub(r"\W", "", name.lower())]
    for t in list(content_tags)[:3]:        # what happens, e.g. #policechase #lucia
        h = "#" + re.sub(r"\W", "", t.lower())
        if len(h) > 2 and h not in tags:
            tags.append(h)
    tags += [h for h in EXTRA_HASHTAGS if h not in tags]
    return (
        f"{title}\n\n"
        f"🎮 Clip from {site} — go show them love!\n"
        f"Original: {clip['url']}\n\n"
        f"Follow ViceClips for the best GTA 6 clips every day 🌴\n\n"
        + " ".join(tags[:10])
    )


def make_tags(clip):
    name = streamer_name(clip)
    return ["gta 6", "gta vi", "gta 6 funny moments", name, f"{name} gta 6", "twitch clips"]
