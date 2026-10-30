"""promptfoo test generator backed by eval/intake_cases.py."""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def generate_tests(config=None):
    from eval.intake_cases import CASES

    return [
        {"vars": {"message": message}, "assert": [{"type": "equals", "value": expected}]}
        for message, expected in CASES
    ]
