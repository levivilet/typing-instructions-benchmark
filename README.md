# Typing instructions benchmark

Compare retired CPU instructions executed while an editor handles one typed
character on Linux ARM64. The chart reports each editor's median from three
fresh-profile trials, ordered from fewest instructions to most.

The latest complete run is published at
[GitHub Pages](https://levivilet.github.io/typing-instructions-benchmark/).
Every editor result includes the raw hardware counter, trial boundaries, host
metadata, and the input and saved-content evidence. Incomplete matrices and
invalid trials are never published.

## Measurement protocol

- Linux ARM64, Ubuntu 24.04 ARM, X11/Xvfb, one editor per runner. The selected
  matrix is LVCE Editor, VS Code, Zed, Lapce, Geany, and Basic Electron. This is
  the supported ARM artifact subset of the desktop comparison set.
- Each trial opens a fresh empty text file using a fresh HOME and XDG profile.
  Startup and a 10-second settling period happen with counters disabled.
- The external input driver focuses the document and verifies that focus
  belongs to the editor cgroup. It sends exactly one ASCII `x` keypress.
- `perf stat` counts retired user and kernel instructions for the editor's
  cgroup. Counting begins immediately before input dispatch and ends after a
  fixed one-second response window. The editor and its descendants are
  included. Background work during that window is included.
- Launch, fixture setup, focus setup, the input driver, save verification,
  cleanup, the desktop, and the X server are outside the counted cgroup. The
  counter enable/disable control latency is recorded and included.
- After counter cutoff, the harness saves the document and requires the file
  to contain exactly `x`. Geany's native save behavior may add one final line
  feed; this exact case is accepted and the raw content is retained. Focus
  loss, a missing or extra character, a failed save, unsupported or multiplexed
  counters, or an incomplete editor matrix invalidate the trial; no invalid
  value is reported as zero.
- Three trials per editor use fresh application profiles. The chart compares
  the median instruction count per trial. OS filesystem caches may be warm.
- Editor downloads are pinned by version and SHA-256 in
  `config/editors.lock.json`. Raw JSON retains all counts, timings, host and
  protocol metadata, focus evidence, and verified saved contents.

The fixed one-second response window makes the measured interval explicit. It
captures the keypress handling and immediate editor work, while background work
within that window is disclosed rather than attributed to an isolated CPU
event.

## Run locally

The same ARM64 hardware-counter access and editor packages used by CI are
required. On an Ubuntu ARM64 runner with `perf` and the desktop dependencies
installed:

```sh
python3 scripts/install.py
python3 -m unittest discover -s tests
sudo sysctl kernel.perf_event_paranoid=-1
PERF=$(find -L /usr/lib/linux-tools -name perf -type f | sort | tail -n 1)
xvfb-run -a -s '-screen 0 1280x800x24' bash scripts/run.sh lvce "$PERF"
```

Use `python3 scripts/benchmark.py --help` to see trial options.

## CI

Every pull request runs hardware-accounting acceptance, all six editor trials,
and the full-report regression checks on the intended ARM runner matrix. Main
pushes, scheduled runs, and manual runs publish three trials per editor and
deploy the validated report to GitHub Pages. CI does not publish a partial
matrix.
