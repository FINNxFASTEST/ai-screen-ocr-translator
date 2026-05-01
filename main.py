import sys

from app.start_bar import StartBar, is_first_run
from app.main import run


if __name__ == "__main__":
    if is_first_run():
        bar = StartBar()
        if not bar.run():
            sys.exit(0)
    run()
