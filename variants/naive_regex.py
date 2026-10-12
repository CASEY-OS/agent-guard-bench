"""The one-line regex someone writes first. It looks for the famous spellings and nothing else.
Policy C additions are the obvious ones a first attempt would add: reset --hard, a force push,
clean -fd, branch -D, and a whole-tree checkout."""
import re

_NAIVE = re.compile(r"git add (-A|--all|\.)|--no-verify"
                    r"|reset --hard|push (-f|--force)|clean -fd|branch -D|checkout \.")


def decide(command):
    m = _NAIVE.search(command or "")
    return ("block", "naive_regex: matched %r" % m.group(0)) if m else ("allow", "")
