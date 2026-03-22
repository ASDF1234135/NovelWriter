"""Workflow tuning constants."""

# Max unfinished anchors shown in director / planner prompts (sliding window).
VISIBLE_UNACHIEVED_ANCHOR_LIMIT = 5

# Macro: each volume must end up with this many anchors after normalization.
MIN_ANCHORS_PER_VOLUME = 3
MAX_ANCHORS_PER_VOLUME = 5
