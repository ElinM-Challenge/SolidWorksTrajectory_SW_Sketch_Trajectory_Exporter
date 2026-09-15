"""Compatibility entry point for the refactored trajectory exporter."""

from __future__ import annotations

import sys


def main() -> int:
    if "--gui" in sys.argv[1:]:
        sys.argv.remove("--gui")
        from trajectory_export_app.gui import main as gui_main

        return gui_main(sys.argv[1:])

    from trajectory_export_app.core import main as cli_main

    return cli_main()


if __name__ == "__main__":
    raise SystemExit(main())
