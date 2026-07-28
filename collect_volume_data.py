"""
Step 1 of Volume Health Analysis Agent.

- Reads volume directory paths from volume_path_list.txt
- For each path:
    used_gb  = recursive size of that directory
    total_gb = total capacity of the drive the directory lives on
    free_gb  = total_gb - used_gb   (how much of the drive remains for this volume)
    percent  = used_gb / total_gb * 100
- Writes results to VOLUME_USAGE_REPORT.txt and appends to output_usage_history.txt
- Invokes Find_Volume_InUse.exe to discover the currently active TC volume
"""
import os
import subprocess
import time
import configparser
import psutil

BASE_DIR         = os.path.dirname(os.path.abspath(__file__))
CONFIG_FILE      = os.path.join(BASE_DIR, "config.ini")
DATA_DIR         = os.path.join(BASE_DIR, "data")
REPORT_FILE      = os.path.join(DATA_DIR, "VOLUME_USAGE_REPORT.txt")
HISTORY_FILE     = os.path.join(DATA_DIR, "output_usage_history.txt")
CURRENT_VOL_FILE = os.path.join(DATA_DIR, "OUTPUT_Find_Volume_inUse.txt")
PATH_LIST_FILE   = os.path.join(BASE_DIR, "volume_path_list.txt")

os.makedirs(DATA_DIR, exist_ok=True)


def _load_config():
    cfg = configparser.ConfigParser()
    cfg.read(CONFIG_FILE, encoding="utf-8")
    return cfg


def bytes_to_gb(b):
    return round(b / (1024 ** 3), 2)


# ---- Volume path list -------------------------------------------------------

def load_volume_paths():
    """Return list of volume directory paths from volume_path_list.txt."""
    if not os.path.exists(PATH_LIST_FILE):
        raise FileNotFoundError(
            f"volume_path_list.txt not found at: {PATH_LIST_FILE}"
        )
    paths = []
    with open(PATH_LIST_FILE, "r", encoding="utf-8") as f:
        for line in f:
            p = line.strip()
            if p and not p.startswith("#"):
                paths.append(p)
    return paths


# ---- Directory size ---------------------------------------------------------

# ---- Drive root for a path --------------------------------------------------

def _drive_root(path):
    """
    Return the drive root for a path.
    Windows: C:\Jagadish\volumes\DefaultVolume  →  C:\
    POSIX:   /mnt/tc/volumes/DefaultVolume      →  /
    """
    return os.path.splitdrive(os.path.abspath(path))[0] + os.sep


# ---- Collect volume data ----------------------------------------------------

def collect_drives():
    """
    For each path in volume_path_list.txt:
      name     = folder basename  (e.g. DefaultVolume)
      used_gb  = used space on the host drive  (e.g. C:\)
      total_gb = total capacity of the host drive
      free_gb  = free space on the host drive
      percent  = host drive usage %
    The folder name is used as the volume identifier throughout the pipeline.
    """
    paths = load_volume_paths()
    rows  = []

    for vol_path in paths:
        vol_path   = os.path.normpath(vol_path)
        name       = os.path.basename(vol_path)
        drive_root = _drive_root(vol_path)

        try:
            disk = psutil.disk_usage(drive_root)
        except (OSError, PermissionError) as e:
            print(f"[WARN] Could not read drive stats for {drive_root}: {e}")
            continue

        # Derive fstype from partition list
        fstype = ""
        try:
            for part in psutil.disk_partitions(all=False):
                p_root = _drive_root(part.mountpoint or part.device)
                if os.path.normcase(p_root) == os.path.normcase(drive_root):
                    fstype = part.fstype
                    break
        except Exception:
            pass

        rows.append({
            "name":       name,
            "device":     drive_root,
            "mountpoint": vol_path,
            "fstype":     fstype,
            "total_gb":   bytes_to_gb(disk.total),
            "used_gb":    bytes_to_gb(disk.used),
            "free_gb":    bytes_to_gb(disk.free),
            "percent":    round(disk.percent, 2),
        })

        print(f"[OK] {name}: {disk.percent}% used  ({bytes_to_gb(disk.used)}G / {bytes_to_gb(disk.total)}G)  drive: {drive_root}")

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
    print(f"[OK] Volume report written: {REPORT_FILE}")


def append_history(rows):
    ts = time.strftime("%d-%b-%Y %H:%M")
    with open(HISTORY_FILE, "a", encoding="utf-8") as f:
        for r in rows:
            f.write(f"{ts}|{r['name']}|{r['percent']}%\n")
    print(f"[OK] History updated: {HISTORY_FILE}")


# ---- Teamcenter active-volume discovery ------------------------------------

def run_find_volume_exe():
    cfg          = _load_config()
    exe_path     = cfg.get("paths", "find_volume_exe",    fallback="")
    exe_output   = cfg.get("paths", "find_volume_output", fallback="")
    tc_user      = cfg.get("teamcenter", "tc_user",       fallback="")
    tc_password  = cfg.get("teamcenter", "tc_password",   fallback="")
    tc_group     = cfg.get("teamcenter", "tc_group",      fallback="")

    if not exe_path or not os.path.exists(exe_path):
        print(f"[WARN] Find_Volume_InUse.exe not found at: {exe_path}")
        print("       Skipping active-volume discovery. Update config.ini [paths] find_volume_exe.")
        _write_current_volume("UNKNOWN")
        return None

    cmd = [exe_path, f"-u={tc_user}", f"-p={tc_password}", f"-g={tc_group}"]
    print("[...] Running Find_Volume_InUse.exe ...")

    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
        if result.returncode != 0:
            err = (result.stderr or result.stdout or "").strip()
            print(f"[WARN] Find_Volume_InUse.exe exited with code {result.returncode}: {err}")
    except subprocess.TimeoutExpired:
        print("[WARN] Find_Volume_InUse.exe timed out after 120s.")
    except Exception as e:
        print(f"[WARN] Find_Volume_InUse.exe error: {e}")

    volume_name = _read_exe_output(exe_output)
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
    print("  Step 1: Collecting volume directory data")
    print("=" * 60)

    try:
        rows = collect_drives()
    except FileNotFoundError as e:
        print(f"[ERROR] {e}")
        raise SystemExit(1)

    if not rows:
        print("[WARN] No volume paths found in volume_path_list.txt.")
    else:
        write_report(rows)
        append_history(rows)
        print(f"[OK] {len(rows)} volume(s) collected.")

    print()
    print("=" * 60)
    print("  Step 1b: Discovering active Teamcenter volume")
    print("=" * 60)
    run_find_volume_exe()
