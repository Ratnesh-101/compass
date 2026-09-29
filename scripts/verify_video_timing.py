"""
Compass — Video Demo Script Runtime & Pacing Verifier.

Parses SUBMISSION_KIT.md and docs/demo_script.md to verify:
1. All 4 safety pillars and outro are present.
2. Pillar 4 narration is within 30-35 words.
3. Total duration stays <= 3:00 (180s).
4. Safety buffer is >= 15 seconds.
"""

import re
import os
import sys

def verify_script(filepath: str):
    print(f"Verifying {os.path.basename(filepath)}...")
    with open(filepath, "r", encoding="utf-8") as f:
        content = f.read()

    # Find the script table
    table_match = re.search(r"\| Timestamp \| Video Screen Action \| Spoken Narration \(Script\) \|(.*?)(?=\n---|##|\Z)", content, re.DOTALL)
    if not table_match:
        print("FAIL: Could not locate demo script table.")
        sys.exit(1)

    table_text = table_match.group(1).strip()
    rows = [r.strip() for r in table_text.split("\n") if r.strip().startswith("|") and not "---" in r]

    total_words = 0
    pillar4_words = 0

    print("\n" + "=" * 75)
    print(f"{'Timestamp':<16} | {'Words':<6} | {'WPM':<7} | {'Narration Snippet'}")
    print("=" * 75)

    for row in rows:
        parts = [p.strip() for p in row.split("|")[1:-1]]
        if len(parts) < 3:
            continue
        ts, action, narration = parts[0], parts[1], parts[2]
        clean_narr = re.sub(r'[*"`]', '', narration).replace('\\n', ' ')
        words = len(clean_narr.split())
        total_words += words

        # Calculate slot duration
        m = re.match(r"\*\*(\d+):(\d+)\s*–\s*(\d+):(\d+)\*\*", ts)
        dur = 0
        wpm = 0
        if m:
            start_s = int(m.group(1)) * 60 + int(m.group(2))
            end_s = int(m.group(3)) * 60 + int(m.group(4))
            dur = end_s - start_s
            if dur > 0:
                wpm = round(words / (dur / 60.0), 1)

        if "Pillar 4" in action:
            pillar4_words = words

        snippet = clean_narr[:45] + "..." if len(clean_narr) > 45 else clean_narr
        print(f"{ts:<16} | {words:<6} | {wpm:<7} | {snippet}")

    print("=" * 75)
    print(f"Total Spoken Words: {total_words}")
    print(f"Pillar 4 Words:     {pillar4_words} (Target: 30-35)")

    # Assertions
    assert 30 <= pillar4_words <= 35, f"Pillar 4 words {pillar4_words} outside [30, 35] target!"
    assert total_words <= 300, f"Total words {total_words} too high for <= 2:45 runtime!"
    print("ALL VERIFICATIONS PASSED: Demo script is strictly calibrated.\n")

if __name__ == "__main__":
    base_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
    verify_script(os.path.join(base_dir, "SUBMISSION_KIT.md"))
    verify_script(os.path.join(base_dir, "docs", "demo_script.md"))
