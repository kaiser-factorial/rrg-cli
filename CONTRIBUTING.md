# Contributing

1. Create a Python 3.9+ virtual environment.
2. Install `pip install -e '.[dev]'`.
3. Run `pytest` and `python -m build` before proposing a change.

Keep engine behavior study-neutral. Study-specific filenames, construct definitions,
model rosters, and scientific policies belong in project cartridges, not `src/rrg_cli`.
Changes to routing or blinding require a regression test demonstrating both a clean
package and the leak that must be blocked.
