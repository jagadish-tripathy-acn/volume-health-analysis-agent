"""
Step 1 of Volume Health Analysis Agent.

- Reads all local drives via psutil → VOLUME_USAGE_REPORT.txt
- Appends a timestamped snapshot to output_usage_history.txt
- Invokes Find_Volume_InUse.exe (Teamcenter ITK utility) to discover the
  currently active TC volume → OUTPUT_Find_Volume_inUse.txt
"""
import os
import subprocess
import time
import configparser
import psutil

BASE_DIR    = os.path.dirname(os.path.abspath(__file__))
CONFIG_FILE = os.path.join(BASE_DIR, "config.ini")
DATA_DIR    = os.path.join(BASE_DIR, "data")
REPORT_FILE = os.path.join(DATA_DIR, "VOLUME_USAGE_REPORT.txt")
HISTORY_FILE = os.path.join(DATA_DIR, "output_usage_history.txt")
# Local copy of the exe output — so the rest of the pipeline reads from data/
CURRENT_VOL_FILE = os.path.join(DATA_DIR, "OUTPUT_Find_Volume_inUse.txt")

os.makedirs(DATA_DIR, exist_ok=True)


def _load_config():
    cfg = configparser.ConfigParser()
    cfg.read(CONFIG_FILE, encoding="utf-8")
    return cfg


def bytes_to_gb(b):
    return round(b / (1024 ** 3), 2)


# ---- Local drive collection ------------------------------------------------

def collect_drives():
    partitions = psutil.disk_partitions(all=False)
    rows = []
    for p in partitions:
        try:
            usage = psutil.disk_usage(p.mountpoint)
        except PermissionError:
            continue
        label = p.mountpoint.replace("\\", "").replace("/", "").strip(":") or p.device
        rows.append({
            "name":       label,
            "device":     p.device,
            "mountpoint": p.mountpoint,
            "fstype":     p.fstype,
            "total_gb":   bytes_to_gb(usage.total),
            "used_gb":    bytes_to_gb(usage.used),
            "free_gb":    bytes_to_gb(usage.free),
            "percent":    round(usage.percent, 2),
        })
    return rows


def write_report(rows):
    header1 = "Drive | Total (GB) | Used (GB) | % Usage | Free (GB) | Filesystem | Mountpoint"
    header2 = "-" * len(header1)
    with open(REPORT_FILE, "w", encoding="utf-8") as f:
        f.write(header1 + "\n")
        f.write(header2 + "\n")
        for r in rows:
            f.write(
                f"{r['name']} | {r['total_gb']}G | {r['used_gb']}G | "
                f"{r['percent']}% | {r['free_gb']}G | {r['fstype']} | {r['mountpoint']}\n"
            )
    print(f"[OK] Drive report written: {REPORT_FILE}")


def append_history(rows):
    ts = time.strftime("%d-%b-%Y %H:%M")
    with open(HISTORY_FILE, "a", encoding="utf-8") as f:
        for r in rows:
            f.write(f"{ts}|{r['name']}|{r['percent']}%\n")
    print(f"[OK] History updated: {HISTORY_FILE}")


# ---- Teamcenter active-volume discovery ------------------------------------

def run_find_volume_exe():
    """
    Invokes Find_Volume_InUse.exe to discover the currently active TC volume.
    Copies the output file to data/ so all pipeline steps read from one place.
    Returns the volume name string, or None on failure.
    """
    cfg = _load_config()
    exe_path      = cfg.get("paths", "find_volume_exe", fallback="")
    exe_output    = cfg.get("paths", "find_volume_output", fallback="")
    tc_user       = cfg.get("teamcenter", "tc_user",     fallback="")
    tc_password   = cfg.get("teamcenter", "tc_password", fallback="")
    tc_group      = cfg.get("teamcenter", "tc_group",    fallback="")

    if not exe_path or not os.path.exists(exe_path):
        print(f"[WARN] Find_Volume_InUse.exe not found at: {exe_path}")
        print("       Skipping active-volume discovery. Update config.ini [paths] find_volume_exe.")
        _write_current_volume("UNKNOWN")
        return None

    cmd = [exe_path, f"-u={tc_user}", f"-p={tc_password}", f"-g={tc_group}"]
    print(f"[...] Running Find_Volume_InUse.exe ...")

    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
        if result.returncode != 0:
            err = (result.stderr or result.stdout or "").strip()
            print(f"[WARN] Find_Volume_InUse.exe exited with code {result.returncode}: {err}")
    except subprocess.TimeoutExpired:
        print("[WARN] Find_Volume_InUse.exe timed out after 120s.")
    except Exception as e:
        print(f"[WARN] Find_Volume_InUse.exe error: {e}")

    # Read the volume name from the exe's own output file
    volume_name = _read_exe_output(exe_output)

    # Mirror into data/ so the rest of the pipeline has a single source
    _write_current_volume(volume_name or "UNKNOWN")

    if volume_name:
        print(f"[OK] Current TC volume: {volume_name}")
    return volume_name


def _read_exe_output(path):
    if path and os.path.exists(path):
        with open(path, "r", encoding="utf-8", errors="ignore") as f:
            line = f.readline().strip()
            return line if line else None
    return None


def _write_current_volume(name):
    with open(CURRENT_VOL_FILE, "w", encoding="utf-8") as f:
        f.write(name + "\n")


# ---- Entry point -----------------------------------------------------------

if __name__ == "__main__":
    print("=" * 60)
    print("  Step 1: Collecting local drive data")
    print("=" * 60)

    rows = collect_drives()
    if not rows:
        print("[WARN] No accessible drives found.")
    else:
        write_report(rows)
        append_history(rows)
        print(f"[OK] {len(rows)} drive(s) collected.")

    print()
    print("=" * 60)
    print("  Step 1b: Discovering active Teamcenter volume")
    print("=" * 60)
    run_find_volume_exe()
