"""What the slop check has to catch, and what it must leave alone.

The false-positive cases matter as much as the catches. A check that
flags a real dependency name or a regex needle gets switched off, and
then it is not checking anything.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from kiln import slop  # noqa: E402

EM = chr(0x2014)
ARROW = chr(0x2192)
CURLY = chr(0x2019)
BULLET = chr(0x2022)
ROBOT = chr(0x1F916)

# label, text, kind, expected blocking count (None means at least one)
CASES = [
    ("em dash", "a sentence %s with a dash" % EM, "prose", 1),
    ("arrow", "step one %s step two" % ARROW, "prose", 1),
    ("curly quote", "it%ss fine" % CURLY, "prose", 1),
    ("bullet character", "%s an item" % BULLET, "prose", 1),
    ("robot emoji", "done %s" % ROBOT, "prose", 1),
    ("banned phrase", "this will seamlessly help", "prose", 2),
    ("marketing verb", "we elevate the workflow", "prose", 1),
    ("not just but", "Not just a parser, but a platform.", "prose", 1),
    ("co-author trailer", "Co-Authored-By: someone", "prose", 1),
    ("tool attribution", "Generated with Codex", "prose", 1),
    ("ai generated", "this is ai-generated text", "prose", 1),

    ("plain human prose", "I wrote this to stop losing saved links.", "prose", 0),
    ("short code comment", "# read the file\nx = 1\n", "code", 0),
    ("dependency name is a warning only",
     "install langchain-openai and anthropic sdk", "prose", 0),
    ("suppressed needle line",
     'SEP = re.compile("[%s]")  # slop: allow' % EM, "code", 0),
    ("normal sentence with the word but",
     "It works, but the tests need pytest installed.", "prose", 0),
]

LONG_COMMENT = "\n".join(["# line %d of explanation" % i for i in range(6)])
DENSE = "\n".join(["# note %d" % i for i in range(9)] +
                  ["x%d = %d" % (i, i) for i in range(25)])


def main() -> int:
    bad = 0
    for label, text, kind, want in CASES:
        got = len(slop.blocking(slop.check_text(text, "t", kind)))
        ok = (got >= 1) if want is None else (got == want)
        if not ok:
            bad += 1
            print("  FAIL  %-34s -> %d blocking, want %s" % (label, got, want))
        else:
            print("  ok    %-34s -> %d blocking" % (label, got))

    for label, text, want in (("long comment block", LONG_COMMENT, True),
                              ("high comment density", DENSE, True)):
        got = len(slop.blocking(slop.check_text(text, "t.py", "code"))) > 0
        if got != want:
            bad += 1
            print("  FAIL  %-34s -> %s, want %s" % (label, got, want))
        else:
            print("  ok    %-34s -> caught" % label)

    # The writers are only told what voice_rules names, so it has to name all.
    rules = slop.voice_rules()
    untold = [p for p in slop.BANNED_PHRASES if p not in rules]
    if untold:
        bad += 1
        print("  FAIL  %-34s -> never told: %s" % ("every banned phrase is told", untold))
    else:
        print("  ok    %-34s -> %d named" % ("every banned phrase is told",
                                            len(slop.BANNED_PHRASES)))

    n = len(CASES) + 3
    print()
    print("%d/%d pass" % (n - bad, n))
    return 1 if bad else 0


if __name__ == "__main__":
    raise SystemExit(main())
