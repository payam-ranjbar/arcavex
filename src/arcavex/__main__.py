"""Make ``python -m arcavex`` the command line.

When ``arcavex`` is not on PATH — the usual state right after a pip install into a venv nobody
activated — an assistant's first guess is ``python -m arcavex``. Until now that failed with
"No module named arcavex.__main__" while the working spelling, ``python -m arcavex.clients.cli``,
was one nobody guesses. Both now work; the console script stays the primary entry point.
"""

from arcavex.clients.cli import main

if __name__ == "__main__":
    main()
