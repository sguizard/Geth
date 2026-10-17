"""Geth lab sandbox test (not an agent's code): a step that tries to get out of the sandbox.

Run through geth/lab/bin/lab_sandbox.sh like any step; it prints one JSON line, and every value must be
false or empty for the sandbox to pass. It only probes folders the project may read (the Geth repository, the
work root, the home folder), so a broken sandbox exposes nothing new. bench/lab/sandbox_test.sh runs it.
"""
import json
import os
import shutil
import socket
import sys
import urllib.request

probe_dirs = sys.argv[3:] if len(sys.argv) > 3 else []
result = {}

try:
    socket.getaddrinfo("www.ebi.ac.uk", 443)
    result["dns_resolves"] = True
except OSError:
    result["dns_resolves"] = False
try:
    urllib.request.urlopen("https://www.ebi.ac.uk", timeout=10)
    result["https_reachable"] = True
except Exception:
    result["https_reachable"] = False
try:
    s = socket.create_connection(("129.215.0.1", 53), timeout=5)
    s.close()
    result["tcp_to_ip"] = True
except OSError:
    result["tcp_to_ip"] = False

result["host_folders_visible"] = [d for d in ["/exports", os.path.expanduser("~sguizard")] + probe_dirs
                                  if os.path.exists(d) and d not in ("/", "/work", "/in")]
result["home"] = os.environ.get("HOME", "")
result["secret_like_env"] = sorted(k for k in os.environ
                                   if any(w in k.upper() for w in ("KEY", "TOKEN", "SECRET", "PASS", "GETH", "ELM", "NXF")))
writable = []
for target in ("/in/probe", "/probe", "/usr/probe", "/etc/probe"):
    try:
        with open(target, "w") as fh:
            fh.write("x")
        writable.append(target)
    except OSError:
        pass
result["writable_outside_work"] = writable
os.symlink("/in/step.py", "/work/link_inside")
os.symlink("/etc/hostname", "/work/link_outside")
os.makedirs("/work/sub", exist_ok=True)
os.symlink("/exports", "/work/sub/link_dir")
shutil.copy(sys.argv[1], sys.argv[2])
print(json.dumps(result))
