"""The reel path, pinned at the places it actually broke.

Every reel in the 2026-09-24 run failed with "browser loaded the page but
found no media" while every carousel worked. The cause was not the network
and not the model: a reel's <video> element carries a blob: url, the fetcher
refuses that protocol, and the exception was swallowed by a bare except.

Nothing here opens a browser. The two pieces that were wrong are pure
functions of a url and some bytes, so they are tested as such.
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from kiln import acquire  # noqa: E402

results: list[bool] = []


def check(label: str, passed: bool, detail: str = "") -> None:
    results.append(passed)
    print(("  ok    " if passed else "  FAIL  ") + label
          + (("\n        " + detail) if detail and not passed else ""))


BASE = ("https://scontent-ord5-1.cdninstagram.com/o1/v/t2/f2/m367/AQOP5Oah"
        "?efg=eyJ2ZW5jb2RlX3RhZyI6Inh4In0&_nc_cat=103")


def test_range_stripping() -> None:
    """The whole asset, not the slice the player asked for."""
    print("asking for the whole file instead of a byte range")

    ranged = BASE + "&bytestart=0&byteend=180215"
    got = acquire._full_asset(ranged)
    check("bytestart is dropped", "bytestart" not in got, got)
    check("byteend is dropped", "byteend" not in got, got)
    check("the rest of the query survives", "_nc_cat=103" in got, got)
    check("the signing param survives", "efg=" in got, got)
    check("the host and path are untouched",
          got.startswith("https://scontent-ord5-1.cdninstagram.com/o1/v/t2/f2/m367/"),
          got)

    plain = BASE
    check("a url with no range is returned unchanged",
          acquire._full_asset(plain) == plain, acquire._full_asset(plain))


def _box(name: bytes, handler: bytes = b"") -> bytes:
    """A minimal hdlr box: size, name, 8 bytes of padding, handler type."""
    return b"\x00\x00\x00\x20" + name + (b"\x00" * 8) + handler


def test_track_detection() -> None:
    """Which rendition is the picture and which is the sound."""
    print("telling a video rendition from an audio one")

    video_only = b"\x00\x00\x00\x18ftypmp42" + _box(b"hdlr", b"vide")
    audio_only = b"\x00\x00\x00\x18ftypmp42" + _box(b"hdlr", b"soun")
    both = video_only + _box(b"hdlr", b"soun")

    check("a video rendition reads as video", acquire._mp4_tracks(video_only) == (True, False),
          str(acquire._mp4_tracks(video_only)))
    check("an audio rendition reads as audio", acquire._mp4_tracks(audio_only) == (False, True),
          str(acquire._mp4_tracks(audio_only)))
    check("a muxed file reads as both", acquire._mp4_tracks(both) == (True, True),
          str(acquire._mp4_tracks(both)))

    # The first version of this looked for the bytes "vide" anywhere in the
    # file. Twelve megabytes of compressed video contains them by accident.
    noise = b"\x00\x00\x00\x18ftypmp42" + b"junk vide soun junk" * 500
    check("the four bytes appearing by chance are not a track",
          acquire._mp4_tracks(noise) == (False, False),
          str(acquire._mp4_tracks(noise)))


class _FakeCtx:
    """Stands in for the browser context so no network is touched."""

    def __init__(self, bodies: dict):
        self.bodies = bodies
        self.asked: list[str] = []

    class _Resp:
        def __init__(self, data): self._data = data
        def body(self): return self._data

    @property
    def request(self):
        return self

    def get(self, url, timeout=0):
        self.asked.append(url)
        if url not in self.bodies:
            raise RuntimeError("404")
        return self._Resp(self.bodies[url])


def test_save_video(tmp: Path) -> None:
    print("saving the reel from what the network carried")

    vid = b"\x00\x00\x00\x18ftypmp42" + _box(b"hdlr", b"vide") + b"\x00" * 4000
    aud = b"\x00\x00\x00\x18ftypmp42" + _box(b"hdlr", b"soun") + b"\x00" * 400
    frag = b"\x00\x00\x02\xbcmoof" + b"\x00" * 2000           # no ftyp

    # A blob url with nothing on the network is the exact 2026-09-24 failure.
    ctx = _FakeCtx({})
    got, why = _save_video(ctx, ["blob:https://www.instagram.com/abc"], [],
                           tmp, "sc1", 1000)
    check("a blob url with no network mp4 fails with a real reason",
          got == "" and "in memory" in why, f"{got!r} {why!r}")
    check("and it is not the old catch-all message",
          "found no media" not in why, why)

    # The real shape: ranged urls on the network, whole files behind them.
    ranged_v = "https://cdn/x.mp4?bytestart=0&byteend=99"
    ranged_a = "https://cdn/y.mp4?bytestart=0&byteend=99"
    ctx = _FakeCtx({"https://cdn/x.mp4": vid, "https://cdn/y.mp4": aud})
    got, why = _save_video(ctx, ["blob:https://www.instagram.com/abc"],
                           [ranged_v, ranged_a], tmp, "sc2", 1000)
    check("the range params are stripped before fetching",
          all("bytestart" not in u for u in ctx.asked), str(ctx.asked))
    check("a file is saved", bool(got) and Path(got).exists(), f"{got!r} {why!r}")

    # Fragments are not files, however many of them arrive.
    ctx = _FakeCtx({"https://cdn/z.mp4": frag})
    got, why = _save_video(ctx, [], ["https://cdn/z.mp4?bytestart=0"],
                           tmp, "sc3", 1000)
    check("a fragment with no ftyp box is refused", got == "", f"{got!r}")
    check("and says so specifically", "fragment" in why, why)


def main() -> int:
    import tempfile
    test_range_stripping()
    test_track_detection()
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as t:
        test_save_video(Path(t))
    print()
    print("%d/%d pass" % (sum(results), len(results)))
    return 0 if all(results) else 1


_save_video = acquire._save_video

if __name__ == "__main__":
    raise SystemExit(main())
