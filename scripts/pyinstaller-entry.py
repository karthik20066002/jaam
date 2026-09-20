"""PyInstaller entry point: keeps ``jaam`` importable as a package.

Building ``src/jaam/cli.py`` (or ``__main__.py``) directly makes PyInstaller
treat it as a top-level script, which breaks the package's relative imports.
This shim lives outside the package and uses an absolute import instead.
"""

from jaam.cli import main

if __name__ == "__main__":
    raise SystemExit(main())
