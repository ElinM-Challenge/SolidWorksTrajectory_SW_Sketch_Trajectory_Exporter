from __future__ import annotations

import sys


def main() -> int:
    if sys.argv[1:] and sys.argv[1] == "--worker":
        from trajectory_export_app.worker import main as worker_main

        return worker_main(sys.argv[2:])

    from trajectory_export_app.gui_fluent_workspace import main as gui_main

    return gui_main(sys.argv[1:])


if __name__ == "__main__":
    raise SystemExit(main())
