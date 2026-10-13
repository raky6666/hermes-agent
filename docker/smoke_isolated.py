"""Run inside the Compose service; no Telegram or model credentials needed."""
import os
from pathlib import Path
import subprocess
import sys

assert os.getuid() == 10001 and os.getgid() == 10001
assert not Path("/var/run/docker.sock").exists()
assert "NoNewPrivs:\t1" in Path("/proc/self/status").read_text()
assert "CapEff:\t0000000000000000" in Path("/proc/self/status").read_text()
try:
    Path("/opt/hermes/.smoke-write").write_text("unexpected")
except OSError:
    pass
else:
    raise AssertionError("Application directory must be read-only")
marker = Path("/opt/data/workspace/.compose-smoke")
if "--verify-persistence" in sys.argv:
    assert marker.read_text() == "persistent"
    marker.unlink()
else:
    marker.write_text("persistent")
    Path("/tmp/hermes-smoke").write_text("temporary")
    subprocess.run(["hermes", "--help"], check=True, stdout=subprocess.DEVNULL)
    try:
        subprocess.run(["agent-browser", "open", "data:text/html,<h1>Hermes container browser</h1>"],
                       check=True, timeout=60)
        snapshot = subprocess.check_output(["agent-browser", "snapshot"], text=True, timeout=30)
        assert "Hermes container browser" in snapshot
    finally:
        subprocess.run(["agent-browser", "close"], timeout=30, check=False)
print("Isolated runtime smoke check passed.")
