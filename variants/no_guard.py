"""Baseline: no guard at all. Allows every command."""


def decide(command):
    return "allow", ""
