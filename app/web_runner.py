import os
import sys
import time

from dotenv import load_dotenv
from flask import Flask, render_template, jsonify

load_dotenv(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), ".env"))

BASE_DIR  = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA_DIR  = os.path.join(BASE_DIR, "data")
sys.path.insert(0, BASE_DIR)

REPORT_FILE      = os.path.join(DATA_DIR, "VOLUME_USAGE_REPORT.txt")
HISTORY_FILE     = os.path.join(DATA_DIR, "output_usage_history.txt")
HEALTH_FILE      = os.path.join(DATA_DIR, "OUTPUT_health_report.txt")
CURRENT_VOL_FILE = os.path.join(DATA_DIR, "OUTPUT_Find_Volume_inUse.txt")
SWITCH_LOG_FILE      = os.path.join(DATA_DIR, "OUTPUT_switch_log.txt")
SWITCH_HISTORY_FILE  = os.path.join(DATA_DIR, "OUTPUT_switch_history.txt")
AGENT_SUMMARY_FILE   = os.path.join(DATA_DIR, "OUTPUT_agent_summary.txt")

THRESHOLD_CRITICAL = 90
THRESHOLD_MODERATE = 60

app = Flask(__name__)
app.secret_key = "vha_secret_2025"


# ---------- helpers ----------------------------------------------------------

def _parse_report():
    drives = []
    if not os.path.exists(REPORT_FILE):
        return drives
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


def _classify(percent):
    if percent >= THRESHOLD_CRITICAL:
        return "critical"
    if percent >= THRESHOLD_MODERATE:
        return "moderate"
    return "healthy"


def _read_current_volume():
    if not os.path.exists(CURRENT_VOL_FILE):
        return None
    with open(CURRENT_VOL_FILE, "r", encoding="utf-8", errors="ignore") as f:
        val = f.readline().strip()
    return val if val and val != "UNKNOWN" else None


# ---------- page routes ------------------------------------------------------

@app.route("/")
def index():
    return render_template("main.html")


@app.route("/home")
def load_home():
    return render_template("home.html")


# ---------- data API routes --------------------------------------------------

@app.route("/get_all_drives")
def get_all_drives():
    drives = _parse_report()
    current = _read_current_volume()
    for d in drives:
        d["status"] = _classify(d["percent"])
        d["is_current_tc_vol"] = (d["name"] == current)
    return jsonify({"drives": drives})


@app.route("/get_critical_drive")
def get_critical_drive():
    """Most-used drive for the summary card."""
    drives = _parse_report()
    if not drives:
        return jsonify({"drive": None})
    worst = max(drives, key=lambda d: d["percent"])
    worst["status"] = _classify(worst["percent"])
    return jsonify({"drive": worst})


@app.route("/get_current_volume")
def get_current_volume():
    """Active Teamcenter volume discovered by Find_Volume_InUse.exe."""
    current = _read_current_volume()
    drives = _parse_report()
    vol_data = next((d for d in drives if d["name"] == current), None)
    return jsonify({
        "name":    current or "UNKNOWN",
        "found":   vol_data is not None,
        "percent": vol_data["percent"]  if vol_data else None,
        "used_gb": vol_data["used_gb"]  if vol_data else None,
        "total_gb":vol_data["total_gb"] if vol_data else None,
        "free_gb": vol_data["free_gb"]  if vol_data else None,
        "status":  _classify(vol_data["percent"]) if vol_data else "unknown",
    })


@app.route("/get_available_drives")
def get_available_drives():
    current = _read_current_volume()
    drives  = _parse_report()
    available = [d for d in drives if d["percent"] < THRESHOLD_MODERATE and d["name"] != current]
    status = (
        "Action Required — Sufficient free drives not available"
        if len(available) < 2
        else "Sufficient drives available"
    )
    return jsonify({"drives": available, "status": status})


@app.route("/get_drive_category_counts")
def get_drive_category_counts():
    drives = _parse_report()
    high     = sum(1 for d in drives if d["percent"] >= THRESHOLD_CRITICAL)
    moderate = sum(1 for d in drives if THRESHOLD_MODERATE <= d["percent"] < THRESHOLD_CRITICAL)
    healthy  = sum(1 for d in drives if d["percent"] < THRESHOLD_MODERATE)
    return jsonify({"high": high, "moderate": moderate, "healthy": healthy})


@app.route("/get_health_report")
def get_health_report():
    content = ""
    if os.path.exists(HEALTH_FILE):
        with open(HEALTH_FILE, "r", encoding="utf-8", errors="ignore") as f:
            content = f.read()
    return jsonify({"data": content or "Health report not found. Run run_analysis.bat first."})


@app.route("/get_switch_log")
def get_switch_log():
    """Contents of the last volume-switch execution log."""
    if not os.path.exists(SWITCH_LOG_FILE):
        return jsonify({"data": "", "exists": False})
    with open(SWITCH_LOG_FILE, "r", encoding="utf-8", errors="ignore") as f:
        content = f.read()
    return jsonify({"data": content, "exists": True})


@app.route("/get_switch_history")
def get_switch_history():
    """Full history of all past volume switches, oldest first."""
    if not os.path.exists(SWITCH_HISTORY_FILE):
        return jsonify({"data": "", "exists": False})
    with open(SWITCH_HISTORY_FILE, "r", encoding="utf-8", errors="ignore") as f:
        content = f.read()
    return jsonify({"data": content, "exists": True})


@app.route("/get_last_update")
def get_last_update():
    target = HEALTH_FILE if os.path.exists(HEALTH_FILE) else REPORT_FILE
    if not os.path.exists(target):
        return jsonify({"last_update": "N/A"})
    mod_time  = os.path.getmtime(target)
    formatted = time.strftime("%d-%b-%Y %I:%M %p", time.localtime(mod_time))
    return jsonify({"last_update": formatted})


@app.route("/get_usage_history")
def get_usage_history():
    if not os.path.exists(HISTORY_FILE):
        return jsonify({"data": ""})
    with open(HISTORY_FILE, "r", encoding="utf-8", errors="ignore") as f:
        content = f.read()
    return jsonify({"data": content})


@app.route("/collect_volume_data", methods=["POST"])
def collect_volume_data():
    """Collect fresh volume data independently of run_analysis.bat."""
    try:
        import collect_volume_data as cvd
        rows = cvd.collect_drives()
        if not rows:
            return jsonify({"ok": False, "error": "No volume paths found in volume_path_list.txt"})
        cvd.write_report(rows)
        cvd.append_history(rows)
        cvd.run_find_volume_exe()
        return jsonify({"ok": True, "volumes": len(rows)})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500


@app.route("/get_agent_summary")
def get_agent_summary():
    """Latest AI-generated health summary from agent_runner.py."""
    if not os.path.exists(AGENT_SUMMARY_FILE):
        return jsonify({"data": "", "exists": False})
    with open(AGENT_SUMMARY_FILE, "r", encoding="utf-8", errors="ignore") as f:
        content = f.read()
    return jsonify({"data": content, "exists": True})


@app.route("/run_agent_summary", methods=["POST"])
def run_agent_summary():
    """Run the Claude agent and return the generated summary."""
    try:
        from agent_runner import run_agent
        summary = run_agent()
        return jsonify({"ok": True, "summary": summary})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500


@app.route("/get_alert_message")
def get_alert_message():
    drives   = _parse_report()
    current  = _read_current_volume()
    critical = [d for d in drives if d["percent"] >= THRESHOLD_CRITICAL]
    if not critical:
        return jsonify({"message": "", "type": "none"})
    names = ", ".join(d["name"] for d in critical)

    # Escalate message if the active TC volume itself is critical
    current_drive = next((d for d in critical if d["name"] == current), None)
    if current_drive:
        msg = (
            f"CRITICAL: Active TC volume '{current}' is at {current_drive['percent']}% — "
            "a volume switch has been attempted. Check the Switch Log for results."
        )
        return jsonify({"message": msg, "type": "switch"})

    msg = (
        f"WARNING: {len(critical)} drive(s) at or above {THRESHOLD_CRITICAL}% — {names}. "
        "Immediate action required."
    )
    return jsonify({"message": msg, "type": "warning"})


if __name__ == "__main__":
    app.run(debug=True, port=5001)
