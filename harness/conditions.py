"""Display names for stable experiment IDs; never use labels as storage keys."""

CONDITION_LABELS = {
    "baseline": "Baseline",
    "policy": "Advisor-only",
    "verification": "Verification-only",
    "full": "Full",
}


def condition_label(condition):
    return CONDITION_LABELS.get(condition, condition)
