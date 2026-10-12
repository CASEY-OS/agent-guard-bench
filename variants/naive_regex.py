"""The one-line regex someone writes first. It looks for the two famous spellings and nothing else."""
import re

_NAIVE = re.compile(r"git add (-A|--all|\.)|--no-verify")


def decide(command):
    m = _NAIVE.search(command or "")
    return ("block", "naive_regex: matched %r" % m.group(0)) if m else ("allow", "")
