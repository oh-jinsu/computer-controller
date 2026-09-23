"""stdio entry point; keep tunnel credentials out of downloader/FFmpeg children."""
import os
from pathlib import Path
import sys

for name in ("CONTROL_PLANE_API_KEY", "OPENAI_API_KEY", "OPENAI_ADMIN_KEY"):
    os.environ.pop(name, None)

from mac_bridge.server import main

if __name__ == "__main__":
    sys.argv = [sys.argv[0], "--root", str(Path(__file__).resolve().parent)]
    main()
