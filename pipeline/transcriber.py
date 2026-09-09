from __future__ import annotations

import subprocess
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import config
from faster_whisper import WhisperModel


class NoAudioError(RuntimeError):
    """The file carries no audio stream, so there is nothing to transcribe."""


def _has_audio_stream(path: str) -> bool | None:
    """True / False if ffprobe can tell, None if it can't be asked."""
    try:
        proc = subprocess.run(
            ["ffprobe", "-v", "error", "-select_streams", "a",
             "-show_entries", "stream=index", "-of", "csv=p=0", path],
            capture_output=True, text=True, timeout=30,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    return bool(proc.stdout.strip()) if proc.returncode == 0 else None


def transcribe(video_path: str) -> dict:
    # faster-whisper reports a file with no audio stream as `tuple index out of
    # range`, which is what sent a capture to skipped.md on 2026-08-21 with no
    # usable clue. Instagram carousel video slides are frequently muted, so this
    # is common, not exotic — name it before Whisper gets a chance to.
    if _has_audio_stream(video_path) is False:
        raise NoAudioError("no audio track")

    model = WhisperModel(
        config.WHISPER_MODEL,
        device=config.WHISPER_DEVICE,
        compute_type=config.WHISPER_COMPUTE,
    )

    segments_gen, info = model.transcribe(
        video_path, beam_size=5, language=config.WHISPER_LANGUAGE
    )

    # Materialize the generator while the model is alive — consuming it later
    # after del model causes a CTranslate2 fault.
    segments = [
        {"start": float(s.start), "end": float(s.end), "text": s.text.strip()}
        for s in segments_gen
    ]
    language = info.language

    del model
    del segments_gen

    transcript = " ".join(seg["text"] for seg in segments).strip()

    return {
        "transcript": transcript,
        "language": language,
        "segments": segments,
    }


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("usage: python pipeline/transcriber.py <video_path>", file=sys.stderr)
        sys.exit(1)
    sys.stdout.reconfigure(encoding="utf-8")
    result = transcribe(sys.argv[1])
    print(f"Language: {result['language']}")
    print()
    print(result["transcript"])
