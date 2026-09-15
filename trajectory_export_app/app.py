from __future__ import annotations

import sys


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    if argv and argv[0] == "--worker":
        from .worker import main as worker_main

        return worker_main(argv[1:])
    from .gui import main as gui_main

    return gui_main(argv)


if __name__ == "__main__":
    raise SystemExit(main())
