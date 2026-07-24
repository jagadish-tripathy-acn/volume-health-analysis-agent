"""
Step 2 of Volume Health Analysis Agent.

- Reads VOLUME_USAGE_REPORT.txt and OUTPUT_Find_Volume_inUse.txt
- Evaluates drive health against thresholds
- If the current active TC volume is at/above critical threshold AND a
  healthier volume exists, invokes switch_volume.py to reassign all groups
- Writes a formatted execution report to data/OUTPUT_health_report.txt
"""
import os
import time
import configparser

BASE_DIR    = os.path.dirname(os.path.abspath(__file__))
CONFIG_FILE = os.path.join(BASE_DIR, "config.ini")
DATA_DIR    = os.path.join(BASE_DIR, "data")
REPORT_FILE      = os.path.join(DATA_DIR, "VOLUME_USAGE_REPORT.txt")
CURRENT_VOL_FILE = os.path.join(DATA_DIR, "OUTPUT_Find_Volume_inUse.txt")
OUTPUT_FILE      = os.path.join(DATA_DIR, "OUTPUT_health_report.txt")

os.makedirs(DATA_DIR, exist_ok=True)


def _load_config():
    cfg = configparser.ConfigParser()
    cfg.read(CONFIG_FILE, encoding="utf-8")
    return cfg


def _threshold(key, default):
    cfg = _load_config()
    try:
        return int(cfg.get("thresholds", key))
    except Exception:
        return default


THRESHOLD_CRITICAL = _threshold("critical", 90)
THRESHOLD_MODERATE = _threshold("moderate", 60)


# ---- Parsers ---------------------------------------------------------------

def parse_report():
    if not os.path.exists(REPORT_FILE):
        raise FileNotFoundError(
            f"Volume report not found: {REPORT_FILE}\nRun collect_volume_data.py first."
        )
    drives = []
    with open(REPORT_FILE, "r", encoding="utf-8") as f:
        lines = f.readlines()[2:]
    for line in lines:
        parts = [p.strip() for p in line.split("|")]
        if len(parts) < 7:
            continue
        try:
            drives.append({
                "name":       parts[0],
                "total_gb":   parts[1],
                "used_gb":    parts[2],
                "percent":    float(parts[3].replace("%", "")),
                "free_gb":    parts[4],
                "fstype":     parts[5],
                "mountpoint": parts[6],
            })
        except ValueError:
            continue
    return drives


def read_current_volume():
    if not os.path.exists(CURRENT_VOL_FILE):
        return None
    with open(CURRENT_VOL_FILE, "r", encoding="utf-8", errors="ignore") as f:
        val = f.readline().strip()
    return val if val and val != "UNKNOWN" else None


# ---- Classification --------------------------------------------------------

def classify(percent):
    if percent >= THRESHOLD_CRITICAL:
        return "CRITICAL"
    if percent >= THRESHOLD_MODERATE:
        return "MODERATE"
    return "HEALTHY"


# ---- Volume switch decision ------------------------------------------------

def _find_next_volume(drives, current_name):
    """Return the first drive below critical threshold that is not the current one."""
    candidates = [
        d for d in drives
        if d["name"] != current_name and d["percent"] < THRESHOLD_CRITICAL
    ]
    if not candidates:
        return None
    return min(candidates, key=lambda d: d["percent"])


def maybe_switch(drives, current_name):
    """
    If the current volume is at or above critical, find the next best volume
    and invoke switch_volume.py.
    Returns (switched: bool, next_volume_name: str|None, log_text: str).
    """
    if not current_name:
        return False, None, "  [SKIP] Active TC volume unknown — skipping switch check."

    current_drive = next((d for d in drives if d["name"] == current_name), None)
    if current_drive is None:
        return False, None, (
            f"  [SKIP] Volume '{current_name}' not found in local drive report — "
            "it may be a network/TC-managed volume not visible to psutil."
        )

    if classify(current_drive["percent"]) != "CRITICAL":
        return False, None, (
            f"  [OK] Current volume '{current_name}' is at {current_drive['percent']}% — "
            "no switch needed."
        )

    next_drive = _find_next_volume(drives, current_name)
    if not next_drive:
        return False, None, (
            f"  [WARN] Current volume '{current_name}' is CRITICAL at "
            f"{current_drive['percent']}% but NO suitable replacement found."
        )

    print(
        f"\n[ACTION] Volume '{current_name}' is at {current_drive['percent']}% "
        f"— switching to '{next_drive['name']}' ({next_drive['percent']}%)"
    )

    from switch_volume import switch_volume as do_switch
    success, log_text = do_switch(current_name, next_drive["name"])
    return True, next_drive["name"], log_text


# ---- Report builder --------------------------------------------------------

def build_report(drives, current_name, switched, next_vol, switch_note):
    ts  = time.strftime("%d-%b-%Y %I:%M %p")
    sep = "=" * 70

    critical = [d for d in drives if classify(d["percent"]) == "CRITICAL"]
    moderate = [d for d in drives if classify(d["percent"]) == "MODERATE"]
    healthy  = [d for d in drives if classify(d["percent"]) == "HEALTHY"]

    lines = [
        sep,
        "     VOLUME HEALTH ANALYSIS REPORT",
        f"     Generated : {ts}",
        sep,
        "",
        f"  Total Drives Scanned : {len(drives)}",
        f"  Critical (>= {THRESHOLD_CRITICAL}%)    : {len(critical)}",
        f"  Moderate ({THRESHOLD_MODERATE}-{THRESHOLD_CRITICAL-1}%) : {len(moderate)}",
        f"  Healthy  (<  {THRESHOLD_MODERATE}%)    : {len(healthy)}",
        "",
        f"  Active TC Volume     : {current_name or 'UNKNOWN'}",
    ]

    if switched:
        lines += [
            f"  Volume Switch        : PERFORMED  ({current_name} -> {next_vol})",
            f"  Switch Status        : See OUTPUT_switch_log.txt for details",
        ]
    else:
        lines += [f"  Volume Switch        : {switch_note.strip()}"]

    lines += ["", sep]

    if critical:
        lines += ["", "  [!] CRITICAL DRIVES — Immediate Action Required", ""]
        for d in critical:
            marker = " <-- ACTIVE TC VOLUME" if d["name"] == current_name else ""
            lines += [
                f"  Drive     : {d['name']}  ({d['mountpoint']}){marker}",
                f"  Usage     : {d['percent']}%   Used: {d['used_gb']}   Total: {d['total_gb']}   Free: {d['free_gb']}",
                f"  Status    : CRITICAL — at or above {THRESHOLD_CRITICAL}% capacity.",
                f"  Action    : Free up space or expand this volume.",
                "",
            ]

    if moderate:
        lines += ["", "  [~] MODERATE DRIVES — Monitor Closely", ""]
        for d in moderate:
            marker = " <-- ACTIVE TC VOLUME" if d["name"] == current_name else ""
            lines += [
                f"  Drive     : {d['name']}  ({d['mountpoint']}){marker}",
                f"  Usage     : {d['percent']}%   Used: {d['used_gb']}   Total: {d['total_gb']}   Free: {d['free_gb']}",
                f"  Status    : MODERATE — between {THRESHOLD_MODERATE}% and {THRESHOLD_CRITICAL-1}%.",
                f"  Action    : Plan cleanup or capacity expansion.",
                "",
            ]

    if healthy:
        lines += ["", "  [OK] HEALTHY DRIVES", ""]
        for d in healthy:
            marker = " <-- ACTIVE TC VOLUME" if d["name"] == current_name else ""
            lines += [
                f"  Drive     : {d['name']}  ({d['mountpoint']}){marker}",
                f"  Usage     : {d['percent']}%   Used: {d['used_gb']}   Total: {d['total_gb']}   Free: {d['free_gb']}",
                "",
            ]

    lines += [sep, "  END OF REPORT", sep]
    return "\n".join(lines)


# ---- Entry point -----------------------------------------------------------

if __name__ == "__main__":
    print("=" * 60)
    print("  Step 2: Analysing volume health")
    print("=" * 60)

    try:
        drives = parse_report()
    except FileNotFoundError as e:
        print(e)
        raise SystemExit(1)

    current_name = read_current_volume()
    print(f"[INFO] Active TC volume: {current_name or 'UNKNOWN'}")

    switched, next_vol, switch_note = maybe_switch(drives, current_name)

    report = build_report(drives, current_name, switched, next_vol, switch_note)

    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        f.write(report)

    print(report)
    print(f"\n[OK] Health report written: {OUTPUT_FILE}")
