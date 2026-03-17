Tests
=====

What these tests do
-------------------
Perform unit tests for the project (under `tests/`) and exercise the logic in `src/`.

Running the tests
-----------------
- Run all tests with:

```bash
uv run pytest && uv run pyright && uv run ruff check .
```

- Run a single test file:

```bash
uv run pytest tests/lib/test_ax25.py
```

Profiling a test run
--------------------
To profile a test run and write a cProfile output file, use the command below.
Replace the test path with whichever test or test module you want to profile.

```bash
uv run python -m cProfile -o output.prof -m pytest
```

Then to view the profile with SnakeViz, run:

```bash
uv run snakeviz -s output.prof
```