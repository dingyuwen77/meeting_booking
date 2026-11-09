"""支持 python -m meeting_reservation 直接运行契约校验。"""

from .cli import main

if __name__ == "__main__":
    raise SystemExit(main())
