"""`python -m client_py` 的入口，转交给交互式 CLI。"""

from .app import main

if __name__ == "__main__":
    raise SystemExit(main())
