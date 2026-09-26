"""Transcribing a saved reel, pinned at the parts that can go wrong quietly.

A reel that no free model could read still has to be read, and until now the
Claude fallback threw its sound away: a post naming four companies out loud
and writing none of them down came out empty. listen.py transcribes the
audio track acquire.py already saves.

Nothing here loads a model. The pieces that can be wrong without anyone
noticing are the file it picks, the cache it trusts, and what it says when
it cannot hear anything, and all three are pure functions of a directory.
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from kiln import listen  # noqa: E402

results: list[bool] = []


def check(label: str, passed: bool, detail: str = "") -> None:
    results.append(passed)
    print(("  ok    " if passed else "  FAIL  ") + label
          + (("\n        " + detail) if detail and not passed else ""))


def _touch(d: Path, name: str, body: bytes = b"x") -> Path:
    p = d / name
    p.write_bytes(body)
    return p


def test_which_file(tmp: Path) -> None:
    """The sound on its own beats the merged file, which beats the picture."""
    print("picking the file with the sound in it")

    d = tmp / "all-three"
    d.mkdir()
    _touch(d, "AB123_video.mp4")
    _touch(d, "AB123_av.mp4")
    _touch(d, "AB123_audio.mp4")
    check("the audio track is preferred",
          listen._pick(d).name == "AB123_audio.mp4", str(listen._pick(d)))

    d2 = tmp / "no-audio-track"
    d2.mkdir()
    _touch(d2, "AB123_video.mp4")
    _touch(d2, "AB123_av.mp4")
    check("the merged file is next", listen._pick(d2).name == "AB123_av.mp4",
          str(listen._pick(d2)))

    d3 = tmp / "picture-only"
    d3.mkdir()
    _touch(d3, "AB123_video.mp4")
    check("the picture is the last resort",
          listen._pick(d3).name == "AB123_video.mp4", str(listen._pick(d3)))

    d4 = tmp / "a-carousel"
    d4.mkdir()
    _touch(d4, "AB123_01.jpg")
    _touch(d4, "AB123.pdf")
    check("a carousel has nothing to play", listen._pick(d4) is None,
          str(listen._pick(d4)))


def test_no_media_is_not_the_repo(tmp: Path) -> None:
    """An item with no media must not send this looking through the repo.

    Path("") is Path("."), which is a directory and passes an is_dir()
    guard, so an empty media_dir had it listing the working directory for
    something to transcribe and reporting whatever it found there.
    """
    print("an item with no media saved")

    text, why = listen.transcribe("")
    check("empty media_dir is refused", not text and "no media" in why, why)

    text, why = listen.transcribe(None)
    check("so is None", not text and "no media" in why, why)

    text, why = listen.transcribe(tmp / "was-never-created")
    check("so is a directory that is not there",
          not text and "no media" in why, why)


def test_cache(tmp: Path) -> None:
    """A reel is heard once, however many passes read it."""
    print("the transcript is kept next to the sound")

    d = tmp / "cached"
    d.mkdir()
    _touch(d, "AB123_audio.mp4")
    (d / "transcript.txt").write_text("what the man said", encoding="utf-8")

    text, why = listen.transcribe(d)
    check("a kept transcript comes straight back", text == "what the man said", text)
    check("and no reason is given with it", why == "", why)

    # A silent reel caches as an empty file. Without this it is transcribed
    # again on every pass that reads it, for nothing.
    d2 = tmp / "cached-silent"
    d2.mkdir()
    _touch(d2, "AB123_audio.mp4")
    (d2 / "transcript.txt").write_text("", encoding="utf-8")

    text, why = listen.transcribe(d2)
    check("a silent reel is not listened to twice",
          not text and "heard before" in why, why)


def test_switched_off(tmp: Path) -> None:
    """KILN_LISTEN=0 turns it off without taking a read down."""
    print("turned off")

    d = tmp / "off"
    d.mkdir()
    _touch(d, "AB123_audio.mp4")

    was = listen.OFF
    try:
        listen.OFF = True
        text, why = listen.transcribe(d)
        check("nothing is transcribed", not text, text)
        check("and it says why", "off" in why, why)
    finally:
        listen.OFF = was


def test_model_is_found_by_shape(tmp: Path) -> None:
    """The model is found by the file in it, never by a revision hash.

    A pinned snapshot id rots the first time the cache is refreshed, and
    the failure is silent: no model found, every reel goes unheard.
    """
    print("finding the cached model")

    good = tmp / "snapshot-with-a-model"
    good.mkdir()
    _touch(good, "model.bin")
    bad = tmp / "snapshot-without-one"
    bad.mkdir()

    import os
    was = os.environ.get("KILN_WHISPER_DIR")
    try:
        os.environ["KILN_WHISPER_DIR"] = str(good)
        check("a directory holding model.bin is used",
              listen._model_dir() == str(good), listen._model_dir())

        os.environ["KILN_WHISPER_DIR"] = str(bad)
        check("one without it is not", listen._model_dir() == "",
              listen._model_dir())
    finally:
        if was is None:
            os.environ.pop("KILN_WHISPER_DIR", None)
        else:
            os.environ["KILN_WHISPER_DIR"] = was


def test_reader_is_told_about_the_sound() -> None:
    """The prompt must stop telling Claude it has no audio.

    It said so as a flat fact, so a read would file the speech as unheard
    even with a transcript sitting in front of it.
    """
    print("what the reader is told")

    from kiln import brain
    check("the reader is not told it cannot hear anything",
          "you cannot hear its audio" not in brain.READER, "READER")
    check("it is pointed at the transcript instead",
          "spoken" in brain.READER and "transcribed" in brain.READER, "READER")
    check("and every prompt still formats",
          all(_formats(t) for t in (brain.READER, brain.PLANNER,
                                    brain.WORKER, brain.FINAL)))


def _formats(tmpl: str) -> bool:
    """A stray brace in new wording breaks .format() at the call site."""
    import re
    keys = set(re.findall(r"\{(\w+)\}", tmpl))
    try:
        tmpl.format(**{k: "" for k in keys})
        return True
    except (KeyError, IndexError, ValueError):
        return False


def main() -> int:
    import tempfile
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as t:
        tmp = Path(t)
        test_which_file(tmp)
        test_no_media_is_not_the_repo(tmp)
        test_cache(tmp)
        test_switched_off(tmp)
        test_model_is_found_by_shape(tmp)
    test_reader_is_told_about_the_sound()
    print()
    print("%d/%d pass" % (sum(results), len(results)))
    return 0 if all(results) else 1


if __name__ == "__main__":
    raise SystemExit(main())
