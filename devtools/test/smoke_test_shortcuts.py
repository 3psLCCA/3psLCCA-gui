"""
devtools/test/smoke_test_shortcuts.py

Interactive Human Verification Test for 3psLCCA Project Window Shortcuts.

Usage:
    python devtools/test/smoke_test_shortcuts.py
"""

import sys

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")


TEST_CASES = [
    {
        "id": 1,
        "shortcut": "Ctrl+Shift+N",
        "action": "New Project",
        "menu": "File",
        "question": "Did the 'New Project' dialog / action trigger?",
    },
    {
        "id": 2,
        "shortcut": "Ctrl+Shift+O",
        "action": "Open Project",
        "menu": "File",
        "question": "Did the Home screen / Project Picker appear?",
    },
    {
        "id": 3,
        "shortcut": "Ctrl+S",
        "action": "Save",
        "menu": "File",
        "question": "Did the project save (e.g. status message 'All changes saved')?",
    },
    {
        "id": 4,
        "shortcut": "Ctrl+W",
        "action": "Close Project",
        "menu": "File",
        "question": "Did the project close and return to the Home page?",
    },
    {
        "id": 5,
        "shortcut": "Ctrl+I",
        "action": "Project Info",
        "menu": "Project",
        "question": "Did the Project Information modal open?",
    },
    {
        "id": 6,
        "shortcut": "F2",
        "action": "Rename Project",
        "menu": "Project",
        "question": "Did the Rename Project input dialog prompt open?",
    },
    {
        "id": 7,
        "shortcut": "Ctrl+Shift+S",
        "action": "Save Checkpoint",
        "menu": "Project",
        "question": "Did the 'Save Checkpoint' dialog open?",
    },
    {
        "id": 8,
        "shortcut": "Ctrl+Shift+H",
        "action": "View Checkpoints",
        "menu": "Project",
        "question": "Did the 'Checkpoint Manager' dialog open?",
    },
    {
        "id": 9,
        "shortcut": "Ctrl+H",
        "action": "Version History",
        "menu": "Project",
        "question": "Did the 'Version History / Rollback' dialog open?",
    },
    {
        "id": 10,
        "shortcut": "Ctrl+E",
        "action": "Export Inputs as JSON",
        "menu": "Project → Export",
        "question": "Did the save file dialog open to export inputs JSON?",
    },
    {
        "id": 11,
        "shortcut": "Ctrl+Shift+E",
        "action": "Export Results as JSON",
        "menu": "Project → Export",
        "question": "Did the export results JSON dialog open (if calculation run)?",
    },
    {
        "id": 12,
        "shortcut": "Ctrl+B",
        "action": "Toggle Sidebar",
        "menu": "View",
        "question": "Did the sidebar toggle between collapsed and expanded?",
    },
    {
        "id": 13,
        "shortcut": "Ctrl+L",
        "action": "Logs",
        "menu": "View",
        "question": "Did the System Tracker / Logs window open?",
    },
    {
        "id": 14,
        "shortcut": "F1",
        "action": "Glossary",
        "menu": "Help",
        "question": "Did the Glossary window or documentation dialog open?",
    },
    {
        "id": 15,
        "shortcut": "F5",
        "action": "Calculate",
        "menu": "Top Bar / Global",
        "question": "Did the LCCA calculation start running?",
    },
    {
        "id": 16,
        "shortcut": "Ctrl+Enter (Ctrl+Return)",
        "action": "Calculate",
        "menu": "Top Bar / Global",
        "question": "Did the LCCA calculation start running?",
    },
]


def run_human_test():
    print("=" * 70)
    print("       3psLCCA - Interactive Human Shortcut Verification Test")
    print("=" * 70)
    print("\nPre-requisite:")
    print("  1. Launch the app in a separate terminal: python -m three_ps_lcca_gui")
    print("  2. Open any project into the Project Window.")
    print("  3. Keep the Project Window in focus to test shortcuts.\n")

    input("Press [Enter] when the Project Window is active and ready...")
    print("-" * 70)

    passed = 0
    failed = 0
    skipped = 0
    results = []

    for item in TEST_CASES:
        print(f"\n[Test {item['id']}/{len(TEST_CASES)}] {item['action']} ({item['menu']})")
        print(f"  -> PRESS KEY:   [{item['shortcut']}]")
        print(f"  [?] EXPECTATION: {item['question']}")

        while True:
            choice = input("  Result -> (y)es / (n)o / (s)kip / (q)uit: ").strip().lower()
            if choice in ("y", "yes"):
                passed += 1
                results.append((item, "PASS"))
                print("  [PASS] Checked")
                break
            elif choice in ("n", "no"):
                notes = input("  Describe what happened (optional): ").strip()
                failed += 1
                results.append((item, f"FAIL: {notes}" if notes else "FAIL"))
                print("  [FAIL] Marked failed")
                break
            elif choice in ("s", "skip"):
                skipped += 1
                results.append((item, "SKIPPED"))
                print("  [SKIP] Skipped")
                break
            elif choice in ("q", "quit"):
                print("\nAborting test run...")
                break
            else:
                print("  Please enter 'y', 'n', 's', or 'q'.")

        if choice in ("q", "quit"):
            break

    print("\n" + "=" * 70)
    print("                     TEST SUMMARY REPORT")
    print("=" * 70)
    print(f"Total Tests Run: {len(results)} / {len(TEST_CASES)}")
    print(f"  Passed:  {passed}")
    print(f"  Failed:  {failed}")
    print(f"  Skipped: {skipped}\n")

    if failed > 0:
        print("Failed Shortcuts:")
        for itm, res in results:
            if "FAIL" in res:
                print(f"  * [{itm['shortcut']}] {itm['action']} -> {res}")
    else:
        print("[SUCCESS] All tested shortcuts behaved as expected!")

    print("=" * 70)

    # ── Write log file in same folder with timestamp ──────────────────────────
    from datetime import datetime
    from pathlib import Path

    now = datetime.now()
    timestamp_str = now.strftime("%Y-%m-%d %H:%M:%S")
    filename_ts = now.strftime("%Y%m%d_%H%M%S")

    log_dir = Path(__file__).resolve().parent
    log_file = log_dir / f"shortcut_test_{filename_ts}.log"

    log_lines = [
        "=" * 70,
        "          3psLCCA - Shortcut Human Verification Test Log",
        "=" * 70,
        f"Execution Time: {timestamp_str}",
        f"Test Script:    {Path(__file__).name}",
        f"Results:        {passed} Passed, {failed} Failed, {skipped} Skipped ({len(results)}/{len(TEST_CASES)} total)",
        "-" * 70,
        f"{'#':<3} {'SHORTCUT':<16} {'ACTION':<24} {'MENU':<18} {'STATUS'}",
        "-" * 70,
    ]

    for itm, res in results:
        status_tag = "PASS" if res == "PASS" else ("SKIP" if res == "SKIPPED" else res)
        log_lines.append(
            f"{itm['id']:<3} {itm['shortcut']:<16} {itm['action']:<24} {itm['menu']:<18} {status_tag}"
        )

    log_lines.append("-" * 70)
    if failed == 0 and passed > 0:
        log_lines.append("OVERALL STATUS: SUCCESS - All verified shortcuts passed.")
    elif failed > 0:
        log_lines.append(f"OVERALL STATUS: FAILURE - {failed} shortcut(s) did not behave as expected.")
    else:
        log_lines.append("OVERALL STATUS: INCOMPLETE - No tests marked as passed.")
    log_lines.append("=" * 70)
    log_lines.append("")

    try:
        log_file.write_text("\n".join(log_lines), encoding="utf-8")
        print(f"\n[LOG CREATED] Test log successfully written to:")
        print(f"   {log_file.resolve()}\n")
    except Exception as exc:
        print(f"\n[Warning] Could not write log file: {exc}\n")


if __name__ == "__main__":
    run_human_test()
