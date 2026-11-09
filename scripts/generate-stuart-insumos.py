"""Generate the four local inputs through the persistent preparation graph."""

import sys

from app.cli.preparation_documents import main


if __name__ == "__main__":
    main(["generate", *sys.argv[1:]])
