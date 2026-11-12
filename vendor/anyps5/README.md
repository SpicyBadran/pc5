# AnyPS5 — studied, not vendored

Upstream: <https://github.com/boykopovar/AnyPS5> — licence GPL-2.0-only.

The supplied archive (`AnyPS5-main (1).zip` in the repository root, 19.7 MB) is
kept as received. Its sources are **not** extracted into this repository
because:

* the audit is complete and recorded in `docs/PROJECT_AUDIT.md`,
* the tree is ~93 MB (7,781 files) of sources whose `3rdparty/` directories are
  git submodules that the archive does not contain,
* this environment cannot build it (no CMake, no submodules), so vendoring it
  would add weight without adding testability.

To obtain and build it where the prerequisites exist:

```sh
./tools/fetch_anyps5.sh                 # extracts the supplied archive, or clones upstream
cd vendor/anyps5 && cmake -S . -B build && cmake --build build -j
```

If PC5 later embeds AnyPS5 code (rather than invoking it), the vendored subset
must carry its GPL-2.0-only headers and this notice, and PC5 remains GPL-2.0-only.
