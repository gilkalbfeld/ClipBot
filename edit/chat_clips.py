import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import json
import os
import re
import subprocess
from collections import Counter

from faster_whisper import WhisperModel
from edit.editor import make_vertical

VOD = os.environ["VOD"]
TDL = "tdl/TwitchDownloaderCLI"
OUT = "output"

TOP = 6
BEFORE = 20
AFTER = 10
BUCKET = 10
GAP = 90
MIN_MSGS = 8


def find_vod_id(text):
    match = re.search(r"(\d{6,})", text)
    if not match:
        raise SystemExit("Could not find VOD ID: " + text)
    return match.group(1)


def get_chat(vod_id):
    subprocess.run(
        [
            TDL,
            "chatdownload",
            "--id", vod_id,
            "-o", "chat.json",
            "--collision", "Overwrite"
        ],
        check=True
    )

    with open("chat.json", encoding="utf-8") as file:
        return json.load(file)["comments"]


def find_moments(comments):
    if not comments:
        return []

    counts = Counter(
        int(c["content_offset_seconds"] // BUCKET)
        for c in comments
    )

    n = max(counts) + 1
    arr = [counts.get(i, 0) for i in range(n)]

    candidates = []

    for i, count in enumerate(arr):
        low = max(0, i - 15)
        high = min(n, i + 16)

        window = arr[low:i] + arr[i + 1:high]
        baseline = sum(window) / len(window) if window else 0

        if count >= MIN_MSGS and count >= 2.5 * max(baseline, 1):
            candidates.append(
                (count / max(baseline, 1), i * BUCKET, count)
            )

    candidates.sort(reverse=True)

    picked = []

    for score, timestamp, count in candidates:
        if all(abs(timestamp - p[1]) >= GAP for p in picked):
            picked.append((score, timestamp, count))

        if len(picked) >= TOP:
            break

    return picked


def main():
    vod_id = find_vod_id(VOD)

    comments = get_chat(vod_id)
    print("Chat messages:", len(comments))

    moments = find_moments(comments)
    print("Moments found:", len(moments))

    if not moments:
        print("No interesting chat spikes found.")
        return

    os.makedirs(OUT, exist_ok=True)

    model = WhisperModel(
        "base",
        device="cpu",
        compute_type="int8"
    )

    for number, (score, timestamp, count) in enumerate(moments, 1):
        start = max(0, timestamp - BEFORE)
        end = timestamp + BUCKET + AFTER

        raw = f"{OUT}/raw_{number}.mp4"
        output = f"{OUT}/clip_{number}.mp4"

        print(f"Downloading moment at {timestamp} seconds")

        subprocess.run(
            [
                TDL,
                "videodownload",
                "--id", vod_id,
                "-b", str(start),
                "-e", str(end),
                "-o", raw
            ],
            check=True
        )

        metadata = {
            "source_type": "vod_highlight",
            "vod_url": VOD,
            "vod_id": vod_id,
            "moment_seconds": timestamp,
            "chat_messages": count,
            "chat_spike_score": round(score, 1)
        }

        make_vertical(
            video=raw,
            output=output,
            model=model,
            metadata=metadata,
            layout="blur",
            words_per=3
        )

        os.remove(raw)

        print("Finished:", output)


if __name__ == "__main__":
    main()
