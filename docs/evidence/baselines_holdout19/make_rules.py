"""Writes cc_deny_rules.json. The list was written from the README's three policy paragraphs and the
Claude Code permissions doc ONLY, before any case file was scored, and is not edited after scoring.
Doc facts used (https://code.claude.com/docs/en/permissions): `*` matches any text including spaces and may be
anywhere; a trailing ' *' that is the rule's ONLY wildcard also matches the bare command; `:*` at the end is the same
as ' *'; deny rules also match past leading env assignments; `git -C . push` is NOT matched by `git push *`.
So `git*add ...` (no space after git) is used to also catch `git -C dir add ...` / `git -c k=v add ...`."""
import json
A = [
 "git*add -A*", "git*add --a*", "git*add -u*", "git*add --update*",
 "git*add .", "git*add . *", "git*add ./", "git*add ./ *", "git*add ..", "git*add .. *", "git*add :/*",
 "git add *$(*", "git add *`*",
 "git stage *",
 "git*commit -a*", "git*commit * -a*", "git*commit --all*", "git*commit * --all*",
]
B = [
 "*--no-verify*", "git*commit -n*", "git*commit * -n*",
 "*core.hooksPath*", "*GIT_CONFIG*", "*HUSKY=0*", "*LEFTHOOK=0*", "*SKIP=*", "*pre-commit uninstall*",
 "git*update-ref *", "git*commit-tree *", "git*send-pack *",
 "rm *.git/hooks*", "rm *.githooks*", "rm *.husky*",
 "mv *.git/hooks*", "mv *.githooks*", "mv *.husky*",
 "chmod *.git/hooks*", "chmod *.githooks*", "chmod *.husky*",
 "*>*.git/hooks*", "*>*.githooks*", "*>*.husky*",
]
C = [
 "git*reset *--hard*",
 "git*clean *-*f*",
 "git*checkout -f*", "git*checkout * -f*", "git*checkout --force*", "git*checkout * --force*",
 "git*checkout -B*", "git*checkout * -B*",
 "git*checkout .", "git*checkout . *", "git*checkout *-- .", "git*checkout *-- . *",
 "git*restore .", "git*restore . *",
 "git*switch *--discard-changes*", "git*switch -f*", "git*switch * -f*", "git*switch -C*", "git*switch * -C*",
 "git*push *--force*", "git*push -f*", "git*push * -f*", "git*push * +*", "git*push *--delete*", "git*push * :*",
 "git*push *--mirror*", "git*push *--prune*",
 "git*branch -D*", "git*branch * -D*", "git*branch -f*", "git*branch * -f*", "git*branch *--force*",
 "git*stash drop*", "git*stash clear*", "git*reflog expire*", "git*reflog delete*",
 "git*worktree remove *-f*", "git*worktree remove *--force*",
 "git*rm .", "git*rm . *", "git*rm * .", "git*rm * . *",
 "git*symbolic-ref -d*", "git*symbolic-ref --delete*", "git*read-tree *--reset*", "git*checkout-index *-f*",
 "git*fetch *+*", "*clean.requireForce*", "git*config *remote.*.push*",
 "rm *.git", "rm *.git *", "rm *.git/*",
]
rules = ["Bash(%s)" % r for r in A + B + C]
assert len(rules) == len(set(rules))
json.dump({"permissions": {"deny": rules}}, open("cc_deny_rules.json", "w"), indent=1)
print("A", len(A), "B", len(B), "C", len(C), "total", len(rules))
