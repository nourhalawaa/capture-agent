from __future__ import annotations

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import config
from faster_whisper import WhisperModel


def transcribe(video_path: str) -> dict:
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
