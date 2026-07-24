"""
Executes volume switching via Teamcenter's make_user utility.
Called by check_volume_health.py when the current active volume is at or
above the critical threshold and a healthier volume is available.

Reads group list from config, runs make_user once per group, and writes
a detailed switch log to data/OUTPUT_switch_log.txt.
"""
import os
import subprocess
import time
import configparser

BASE_DIR        = os.path.dirname(os.path.abspath(__file__))
CONFIG_FILE     = os.path.join(BASE_DIR, "config.ini")
DATA_DIR        = os.path.join(BASE_DIR, "data")
SWITCH_LOG      = os.path.join(DATA_DIR, "OUTPUT_switch_log.txt")
SWITCH_HISTORY  = os.path.join(DATA_DIR, "OUTPUT_switch_history.txt")

os.makedirs(DATA_DIR, exist_ok=True)


def _load_config():
    cfg = configparser.ConfigParser()
    cfg.read(CONFIG_FILE, encoding="utf-8")
    return cfg


def _load_groups(group_list_path):
    if not os.path.exists(group_list_path):
        raise FileNotFoundError(f"Group list not found: {group_list_path}")
    with open(group_list_path, "r", encoding="utf-8") as f:
        return [line.strip() for line in f if line.strip()]


def switch_volume(current_volume, next_volume):
    """
    Reassign all TC groups from current_volume to next_volume using make_user.
    Returns (success: bool, log_text: str).
    """
    cfg = _load_config()
    tc_user     = cfg.get("teamcenter", "tc_user")
    tc_password = cfg.get("teamcenter", "tc_password")
    tc_group    = cfg.get("teamcenter", "tc_group")
    make_user   = cfg.get("paths", "make_user_exe")
    group_file  = cfg.get("paths", "group_list_file")

    groups = _load_groups(group_file)

    ts    = time.strftime("%d-%b-%Y %I:%M %p")
    sep   = "=" * 70
    lines = [
        sep,
        "     VOLUME SWITCH LOG",
        f"     Executed : {ts}",
        f"     From     : {current_volume}",
        f"     To       : {next_volume}",
        sep,
        f"  Groups to process : {len(groups)}",
        "",
    ]

    success_count = 0
    fail_count    = 0

    for group in groups:
        cmd = [
            make_user,
            f"-u={tc_user}",
            f"-p={tc_password}",
            f"-g={tc_group}",
            f"-defaultvolume={next_volume}",
            "-update",
            f'-group={group}',
        ]

        try:
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=60,
            )
            if result.returncode == 0:
                lines.append(f"  [OK]   Group: {group}")
                success_count += 1
            else:
                err = (result.stderr or result.stdout or "unknown error").strip()
                lines.append(f"  [FAIL] Group: {group}  —  {err}")
                fail_count += 1
        except subprocess.TimeoutExpired:
            lines.append(f"  [TIMEOUT] Group: {group}")
            fail_count += 1
        except FileNotFoundError:
            lines.append(f"  [ERROR] make_user not found at: {make_user}")
            fail_count += len(groups)
            break
        except Exception as e:
            lines.append(f"  [ERROR] Group: {group}  —  {e}")
            fail_count += 1

    lines += [
        "",
        sep,
        f"  Completed : {success_count} succeeded,  {fail_count} failed",
        f"  Status    : {'SUCCESS' if fail_count == 0 else 'PARTIAL' if success_count > 0 else 'FAILED'}",
        sep,
    ]

    log_text = "\n".join(lines)

    with open(SWITCH_LOG, "w", encoding="utf-8") as f:
        f.write(log_text)

    with open(SWITCH_HISTORY, "a", encoding="utf-8") as f:
        f.write(log_text + "\n\n")

    print(log_text)
    print(f"\n[OK] Switch log written : {SWITCH_LOG}")
    print(f"[OK] History appended   : {SWITCH_HISTORY}")

    return fail_count == 0, log_text


if __name__ == "__main__":
    import sys
    if len(sys.argv) != 3:
        print("Usage: python switch_volume.py <current_volume> <next_volume>")
        raise SystemExit(1)
    switch_volume(sys.argv[1], sys.argv[2])
