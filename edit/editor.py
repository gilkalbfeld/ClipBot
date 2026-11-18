
import json
import os
import subprocess


LAYOUTS = {
    "blur": (
        "[0:v]split=2[bg][fg];"
        "[bg]scale=1080:1920:force_original_aspect_ratio=increase,"
        "crop=1080:1920,boxblur=20:5[bgb];"
        "[fg]scale=1080:-2[fgs];"
        "[bgb][fgs]overlay=(W-w)/2:(H-h)/2"
    ),
    "fill": (
        "[0:v]scale=-2:1920,crop=1080:1920"
    ),
    "bars": (
        "[0:v]scale=1080:-2,"
        "pad=1080:1920:(ow-iw)/2:(oh-ih)/2:black"
    ),
}


def format_time(seconds):
    hours = int(seconds // 3600)
    minutes = int(seconds % 3600 // 60)
    secs = seconds % 60
    return f"{hours}:{minutes:02}:{secs:05.2f}"


def make_ass(model, video, ass_path, words_per=3):
    segments, _ = model.transcribe(
        video,
        word_timestamps=True
    )

    words = [
        word
        for segment in segments
        for word in (segment.words or [])
    ]

    if not words:
        return False

    header = (
        "[Script Info]\n"
        "ScriptType: v4.00+\n"
        "PlayResX: 1080\n"
        "PlayResY: 1920\n\n"
        "[V4+ Styles]\n"
        "Format: Name, Fontname, Fontsize, PrimaryColour, "
        "SecondaryColour, OutlineColour, BackColour, Bold, "
        "Italic, Underline, StrikeOut, ScaleX, ScaleY, "
        "Spacing, Angle, BorderStyle, Outline, Shadow, "
        "Alignment, MarginL, MarginR, MarginV, Encoding\n"
        "Style: Default,DejaVu Sans,64,&H00FFFFFF,&H00FFFFFF,"
        "&H00000000,&H00000000,-1,0,0,0,100,100,0,0,1,"
        "4,0,2,60,60,420,1\n\n"
        "[Events]\n"
        "Format: Layer, Start, End, Style, Name, MarginL, "
        "MarginR, MarginV, Effect, Text\n"
    )

    lines = []

    for i in range(0, len(words), words_per):
        chunk = words[i:i + words_per]

        text = " ".join(
            word.word.strip() for word in chunk
        ).upper()

        lines.append(
            f"Dialogue: 0,"
            f"{format_time(chunk[0].start)},"
            f"{format_time(chunk[-1].end)},"
            f"Default,,0,0,0,,{text}"
        )

    with open(ass_path, "w", encoding="utf-8") as file:
        file.write(header + "\n".join(lines) + "\n")

    return True


def make_vertical(
    video,
    output,
    model,
    metadata=None,
    layout="blur",
    words_per=3
):
    os.makedirs(os.path.dirname(output) or ".", exist_ok=True)

    ass_path = output.rsplit(".", 1)[0] + ".ass"

    has_captions = make_ass(
        model,
        video,
        ass_path,
        words_per
    )

    chain = LAYOUTS[layout]

    if has_captions:
        chain += f",ass={ass_path}"

    chain += "[v]"

    command = [
        "ffmpeg",
        "-y",
        "-i", video,
        "-filter_complex", chain,
        "-map", "[v]",
        "-map", "0:a?",
        "-c:v", "libx264",
        "-preset", "veryfast",
        "-crf", "23",
        "-c:a", "aac",
        "-b:a", "128k",
        "-t", "60",
        output
    ]

    subprocess.run(command, check=True)

    info = metadata or {}
    info["captions"] = has_captions
    info["layout"] = layout
    info["caption_words"] = words_per
    info["video"] = output

    json_path = output.rsplit(".", 1)[0] + ".json"

    with open(json_path, "w", encoding="utf-8") as file:
        json.dump(info, file, indent=2)

    return output
