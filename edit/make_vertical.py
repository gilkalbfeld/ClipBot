
import os
import sys
import random

sys.path.insert(
    0,
    os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
)

from faster_whisper import WhisperModel
from fetch.twitch_clips import get_clips
from edit.download import download
from edit.editor import make_vertical

OUT_DIR = "output"
HOW_MANY = 3

LAYOUTS = ["blur", "fill", "bars"]
CAPTION_WORDS = [2, 3, 4]


def main():
    os.makedirs(OUT_DIR, exist_ok=True)

    model = WhisperModel(
        "base",
        device="cpu",
        compute_type="int8"
    )

    clips = get_clips()[:HOW_MANY]

    for clip in clips:
        print(
            "Working on:",
            clip["broadcaster_name"],
            "-",
            clip["title"]
        )

        src = download(clip)

        if not src:
            print("Download failed, skipping")
            continue

        layout = random.choice(LAYOUTS)
        words_per = random.choice(CAPTION_WORDS)

        output = os.path.join(
            OUT_DIR,
            f"{clip['id']}_vertical.mp4"
        )

        metadata = {
            "source_type": "twitch_clip",
            "title": clip["title"],
            "streamer": clip["broadcaster_name"],
            "source_url": clip["url"],
            "views": clip["view_count"],
            "viral_score": clip["score"],
            "credit": f"Clip from twitch.tv/{clip['broadcaster_name']}"
        }

        make_vertical(
            video=src,
            output=output,
            model=model,
            metadata=metadata,
            layout=layout,
            words_per=words_per
        )

        print("Finished:", output)


if __name__ == "__main__":
    main()
