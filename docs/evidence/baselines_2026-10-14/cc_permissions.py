"""Baseline 1: Claude Code's own Bash(...) permission DENY rules, reimplemented from the docs.

Source: https://code.claude.com/docs/en/permissions (fetched 2026-10-14 with curl as .md; the WebFetch tool was
not available in this session). Quotes the matcher follows:

  * "A `*` in a Bash rule matches any text, including spaces ... A rule with no `*` matches one exact command."
  * "A `*` can go anywhere in the rule: at the start, in the middle, or at the end."
  * "A `*` at the end, with a space before it, also matches the bare command ... That holds only when the
    trailing `*` is the rule's only wildcard: `Bash(* --help *)` matches `npm --help x` but not `npm --help`."
  * "The `:*` suffix is an equivalent way to write a trailing wildcard, so `Bash(ls:*)` matches the same commands
    as `Bash(ls *)`. ... The `:*` form is only recognized at the end of a pattern."
  * "The recognized command separators are `&&`, `||`, `;`, `|`, `|&`, `&`, and newlines. A rule must match each
    subcommand independently."  "Deny and ask rules apply when any subcommand matches them, including a command
    nested inside a subshell, a command substitution, or a control-flow body such as a `for` loop."
  * "The stripped wrappers are `timeout`, `time`, `nice`, `nohup`, and `stdbuf`, plus the shell builtins `command`
    and `builtin`, and zsh's `noglob`." "A deny or ask rule matches past any leading assignment, so `Bash(rm *)`
    in deny still matches `FOO=bar rm -rf tmp/`." "Bare `xargs` is also stripped ... only when `xargs` has no flags."
  * "These rules in deny or ask stop the first form and not the others: `Bash(rm *)` stops `rm -rf build/` and
    not `/bin/rm -rf build/` or `bash -c 'rm -rf build/'`; `Bash(git push *)` does not stop `git -C . push origin
    main`, `git -c push.default=current push origin main`, `git 'push' origin main`."

So this matcher: does NOT look inside `bash -c '...'` / `sh -c` as a command (the quoted text is still part of the
outer subcommand's text, so a wildcard rule such as `*--no-verify*` can still match it, exactly as it would in
Claude Code), does NOT unquote or resolve paths (`/usr/bin/git`, `git 'push'` are not matched), and does NOT
expand variables.

Where the docs are silent I chose the reading most favourable to the baseline (more things blocked):
  (a) a rule is tried against BOTH the subcommand text as written and the text with redirections removed, and
      against every intermediate stage of wrapper / env-assignment stripping (the docs do not say which text is
      matched after stripping; trying all of them can only block more);
  (b) the subcommand splitter is quote-aware (as a real shell parser is), `$(...)`, backticks, `<(...)`,
      `( ... )` subshells and control-flow bodies (if/then/else/do/while/until/{ }) are searched for nested commands;
      a heredoc body is data, not commands (as in a real parser);
  (c) `$VAR` / `${VAR}` words are NOT expanded (docs: variables are not expanded; the doc's own warning lists
      `URL=... && curl $URL` as a bypass), no favourable reading is available there;
  (d) matching is case-sensitive and anchored on the whole subcommand text (docs: "match the whole command text").
"""
import json
import os
import re

HERE = os.path.dirname(os.path.abspath(__file__))
_RULES = None


def load_rules(path=None):
    path = path or os.path.join(HERE, "cc_deny_rules.json")
    with open(path) as f:
        raw = json.load(f)["permissions"]["deny"]
    pats = []
    for r in raw:
        m = re.fullmatch(r"Bash\((.*)\)", r, re.S)
        if m:
            pats.append((r, m.group(1)))
    return pats


# ----------------------------------------------------------------------------- pattern -> matcher
def compile_pattern(pat):
    """Bash rule specifier -> compiled regex, per the documented semantics."""
    if pat.endswith(":*"):                       # ":*" only at the end == trailing " *"
        pat = pat[:-2] + " *"
    star_count = pat.count("*")
    # trailing " *" as the ONLY wildcard also matches the bare command
    if star_count == 1 and pat.endswith(" *"):
        head = re.escape(pat[:-2])
        return re.compile(head + r"(?: .*)?", re.S)
    parts = [re.escape(p) for p in pat.split("*")]
    return re.compile(".*".join(parts), re.S)


# ----------------------------------------------------------------------------- shell-ish splitting
_KEYWORDS = {"if", "then", "else", "elif", "do", "while", "until", "!", "{", "}", "(", ")"}


def _skip_single(s, i):                       # s[i] == "'" -> index after the closing quote
    j = s.find("'", i + 1)
    return len(s) if j < 0 else j + 1


def _match_paren(s, i):
    """s[i] is just after an opening '('. -> index of the matching ')' (or len(s))."""
    depth, n = 1, len(s)
    while i < n:
        c = s[i]
        if c == "\\":
            i += 2
            continue
        if c == "'":
            i = _skip_single(s, i)
            continue
        if c == '"':
            i = _skip_double(s, i)
            continue
        if c == "(":
            depth += 1
        elif c == ")":
            depth -= 1
            if depth == 0:
                return i
        i += 1
    return n


def _skip_double(s, i):
    """s[i] == '"' -> index after the closing quote, honouring \\ escapes and $( ) inside."""
    n = len(s)
    i += 1
    while i < n:
        c = s[i]
        if c == "\\":
            i += 2
            continue
        if c == '"':
            return i + 1
        if c == "$" and s.startswith("$(", i):
            i = _match_paren(s, i + 2) + 1
            continue
        i += 1
    return n


def _nested_in_double(s, out):
    """Collect command substitutions inside a double-quoted string s (without its quotes)."""
    i, n = 0, len(s)
    while i < n:
        c = s[i]
        if c == "\\":
            i += 2
            continue
        if c == "$" and s.startswith("$(", i) and not s.startswith("$((", i):
            j = _match_paren(s, i + 2)
            out.extend(split_commands(s[i + 2:j]))
            i = j + 1
            continue
        if c == "`":
            j = s.find("`", i + 1)
            j = n if j < 0 else j
            out.extend(split_commands(s[i + 1:j]))
            i = j + 1
            continue
        i += 1


def split_commands(s):
    """-> list of subcommand texts (outer ones and every nested one)."""
    s = s.replace("\\\n", "")                      # line continuation
    out, buf = [], []
    i, n = 0, len(s)
    heredocs = []                                   # pending (delimiter, strip_tabs)

    def flush():
        t = "".join(buf).strip()
        buf.clear()
        if t:
            out.append(t)

    while i < n:
        c = s[i]
        if c == "\\":
            buf.append(s[i:i + 2])
            i += 2
            continue
        if c == "'":
            j = _skip_single(s, i)
            buf.append(s[i:j])
            i = j
            continue
        if c == '"':
            j = _skip_double(s, i)
            body = s[i + 1:j - 1] if j - 1 > i else ""
            _nested_in_double(body, out)
            buf.append(s[i:j])
            i = j
            continue
        if c == "`":
            j = s.find("`", i + 1)
            j = n if j < 0 else j
            out.extend(split_commands(s[i + 1:j]))
            buf.append(s[i:j + 1])
            i = j + 1
            continue
        if s.startswith("$((", i):
            j = _match_paren(s, i + 2)
            buf.append(s[i:j + 1])
            i = j + 1
            continue
        if s.startswith("$(", i) or s.startswith("<(", i) or s.startswith(">(", i):
            j = _match_paren(s, i + 2)
            out.extend(split_commands(s[i + 2:j]))
            buf.append(s[i:j + 1])
            i = j + 1
            continue
        if c == "(":                                # subshell: a separator, contents are commands
            flush()
            j = _match_paren(s, i + 1)
            out.extend(split_commands(s[i + 1:j]))
            i = j + 1
            continue
        if c == "#" and (not buf or buf[-1][-1:].isspace()):
            j = s.find("\n", i)
            i = n if j < 0 else j
            continue
        if s.startswith("<<", i) and not s.startswith("<<<", i):
            m = re.match(r"<<(-?)\s*(?:'([^']*)'|\"([^\"]*)\"|(\\?[A-Za-z_][\w]*))", s[i:])
            if m:
                heredocs.append((m.group(2) or m.group(3) or (m.group(4) or "").lstrip("\\"), bool(m.group(1))))
                buf.append(m.group(0))
                i += len(m.group(0))
                continue
        if c == "\n":
            flush()
            i += 1
            while heredocs:                          # the body is data: skip to the terminator line
                delim, strip = heredocs.pop(0)
                while i < n:
                    j = s.find("\n", i)
                    line = s[i:n if j < 0 else j]
                    i = n if j < 0 else j + 1
                    if (line.lstrip("\t") if strip else line) == delim:
                        break
            continue
        if s.startswith("&&", i) or s.startswith("||", i):
            flush()
            i += 2
            continue
        if s.startswith("|&", i):
            flush()
            i += 2
            continue
        if c in ";|":
            flush()
            i += 1
            continue
        if c == "&":
            prev = buf[-1][-1:] if buf else ""
            nxt = s[i + 1:i + 2]
            if prev in (">", "<") or nxt == ">":     # 2>&1, >&2, &>file are redirections, not separators
                buf.append(c)
                i += 1
                continue
            flush()
            i += 1
            continue
        if c == ")":                                # stray close paren (case pattern etc.)
            flush()
            i += 1
            continue
        buf.append(c)
        i += 1
    flush()
    return out


def _strip_keywords(t):
    while True:
        m = re.match(r"(\S+)(?:\s+|$)(.*)", t, re.S)
        if m and m.group(1) in _KEYWORDS:
            t = m.group(2)
            continue
        return t


_ASSIGN = re.compile(r"""^[A-Za-z_][A-Za-z0-9_]*=(?:'[^']*'|"(?:\\.|[^"\\])*"|(?:\\.|[^\s'"\\])*)+\s+""", re.S)


def _strip_one_wrapper(t):
    """-> text after stripping ONE documented wrapper / env assignment, or None."""
    m = _ASSIGN.match(t)
    if m:
        return t[m.end():]
    m = re.match(r"(timeout|time|nice|nohup|stdbuf|command|builtin|noglob|xargs)(?:\s+|$)(.*)", t, re.S)
    if not m:
        return None
    w, rest = m.group(1), m.group(2)
    if w == "command" and re.match(r"-[vV]\b", rest):
        return None                                  # query form, not stripped
    if w == "xargs":
        return None if re.match(r"-", rest) else rest   # only flagless xargs
    if w == "timeout":
        rest = re.sub(r"^(?:-\S+(?:\s+(?=\d))?\s*)*", "", rest)         # options
        rest = re.sub(r"^\d+(?:\.\d+)?[smhd]?\s+", "", rest)            # DURATION
    elif w == "nice":
        rest = re.sub(r"^(?:-n\s*-?\d+|-\d+|--adjustment=\S+)\s+", "", rest)
    elif w == "stdbuf":
        rest = re.sub(r"^(?:-[ioe]\s*\S+\s+|--(?:input|output|error)=\S+\s+)+", "", rest)
    elif w == "time":
        rest = re.sub(r"^(?:-p\s+)", "", rest)
    elif w == "command":
        rest = re.sub(r"^(?:-p\s+)", "", rest)
    return rest


def _strip_redirs(t):
    """Remove unquoted redirection tokens (n>file, >>file, <file, >&n, &>file)."""
    out, i, n = [], 0, len(t)
    while i < n:
        c = t[i]
        if c == "'":
            j = _skip_single(t, i); out.append(t[i:j]); i = j; continue
        if c == '"':
            j = _skip_double(t, i); out.append(t[i:j]); i = j; continue
        if c == "\\":
            out.append(t[i:i + 2]); i += 2; continue
        m = re.match(r"(?:\d*|&)(?:>>|>&|>|<)\s*[^\s;|&]*", t[i:]) if c in "<>&0123456789" and (not out or out[-1][-1:].isspace() or c in "<>&") else None
        if m and m.group(0):
            i += len(m.group(0))
            continue
        out.append(c)
        i += 1
    return re.sub(r"\s+", " ", "".join(out)).strip()


def candidates(sub):
    """Every text a rule is tried against for one subcommand (see docstring (a))."""
    seen, texts = set(), []
    stack = [_strip_keywords(sub)]
    while stack:
        t = stack.pop().strip()
        if not t or t in seen:
            continue
        seen.add(t)
        texts.append(t)
        r = _strip_redirs(t)
        if r and r not in seen:
            stack.append(r)
        nxt = _strip_one_wrapper(t)
        if nxt is not None:
            stack.append(_strip_keywords(nxt))
    return texts


def decide(command, rules=None):
    """-> ("block"|"allow", reason). Deny rules only; there are no allow rules, so everything else is allowed
    (this is the 'what the deny list alone stops' baseline, run non-interactively)."""
    global _RULES
    if rules is None:
        if _RULES is None:
            _RULES = [(r, compile_pattern(p)) for r, p in load_rules()]
        rules = _RULES
    for sub in split_commands(command or ""):
        for text in candidates(sub):
            for name, rx in rules:
                if rx.fullmatch(text):
                    return "block", "cc_permissions: %s matched %r" % (name, text)
    return "allow", ""
