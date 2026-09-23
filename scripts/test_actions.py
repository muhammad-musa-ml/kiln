"""Cases the action rule got wrong at least once."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from kiln.pipeline import derive_action  # noqa: E402

BATCH = ("make a new section called to watch with subsections for types of"
         " videos. Each type might get more videos added. Put these videos in"
         " the right types.")

CASES = [
    # label, note, user_do, medium, expected
    ("youtube in a to-watch batch", {"kind": "course", "action_hint": "learn"},
     BATCH, "youtube", "watch"),
    ("article in the same batch", {"kind": "course", "action_hint": "learn"},
     BATCH, "web", "read"),
    ("youtube, no instruction", {"kind": "tutorial", "action_hint": "learn"},
     "", "youtube", "watch"),
    ("youtube, model said watch", {"kind": "tutorial", "action_hint": "watch"},
     "", "youtube", "watch"),
    ("job post", {"kind": "job", "action_hint": "apply"},
     "find the real posting", "instagram", "apply"),
    ("repo, install ask", {"kind": "repo", "action_hint": "install"},
     "should I install this?", "web", "install"),
    ("genuine build ask", {"kind": "tutorial", "action_hint": "learn"},
     "build me a project from this", "web", "build"),
    ("article, no instruction", {"kind": "tutorial", "action_hint": "read"},
     "", "web", "read"),
    ("ig carousel to learn", {"kind": "tutorial", "action_hint": "learn"},
     "", "instagram", "learn"),
]


def main() -> int:
    bad = 0
    for label, note, do, medium, want in CASES:
        got = derive_action(note, do, medium)
        if got != want:
            bad += 1
            print("  FAIL  %-30s -> %-9s want %s" % (label, got, want))
        else:
            print("  ok    %-30s -> %s" % (label, got))
    print()
    print("%d/%d pass" % (len(CASES) - bad, len(CASES)))
    return 1 if bad else 0


if __name__ == "__main__":
    raise SystemExit(main())
