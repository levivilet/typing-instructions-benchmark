# LVCE first-character instruction investigation

The safe empty-line tokenization fast path reduces first-character instructions modestly. Thirty alternating matched ARM64 trials measured a median of 86,703,158 instructions for the original LVCE v0.122.9 bundle and 86,081,336.5 for the same bundle with only the fast path changed: 0.717% fewer instructions. Mean paired savings were 652,571.7 instructions; the predeclared 95% t interval was 293,768–1,011,375. Twenty-two of thirty pairs improved. This supports a small effect, not the suggested 75% reduction.

## Reproduction and scope

Ubuntu ARM64 Actions runners, kernel 6.17.0-1022-azure, perf 6.8.12; CPU metadata and raw counters are retained in the JSON artifact. Each trial starts a fresh empty fixture/profile, settles for ten seconds, focuses the editor, counts all cgroup user/kernel instructions during one ASCII x and a one-second response window, then saves after cutoff and verifies exactly x. Launch, input driver, X server, verification and cleanup are excluded. Baseline and candidate use identical binaries, dependencies and renderer bundles except the documented editor-worker guard; source and candidate SHA256 values are in the raw comparison JSON. Trial order alternates to limit drift.

Raw measurements are retained in [empty-line-comparison.json](data/empty-line-comparison.json), with [the statistical assessment](data/empty-line-assessment.json).

The artifact is from https://github.com/levivilet/typing-instructions-benchmark/actions/runs/38558837513, head ed947de6c368f5ae5cc1ece57b873af64a162c21, `lvce-empty-line-comparison`. The original pinned Debian SHA256 is 5d7cb83a4bd34034f20a45dcd113f3bdd283a69859d7564e16dbfc4cb7d11478. The original chart run is https://github.com/levivilet/typing-instructions-benchmark/actions/runs/38533404392.

## Attribution

Six no-input controls usually consume ~0.07M instructions versus ~87M for typing; idle background work is not the dominant explanation. A diagnostic type/undo/save warm-up before measurement reduced the median to ~54.3M. That moves first-edit work outside the window and is not a product improvement. These trials are explicitly rejected by the published report validator.

Separate cgroup instruction sampling showed work spread among worker JavaScript/lazy compilation, V8 object serialization/deserialization/allocation, GC, font shaping, and Skia software rasterization. The sampled Electron build ID matches Electron 44.7.0 ARM64 symbols. Thread percentages are not function or repository attribution; profiles use separate trials and do not contaminate comparison counts.

## Change

`GetIncrementalEdits` now returns the existing empty-incremental-edits value when the old line is empty. Incremental tokenization only emits an edit when an existing old token has positive length, so an empty line cannot yield an incremental edit. The normal full-rendering path still tokenizes the new text. Nonempty-line typing retains its existing incremental path. Source PR: https://github.com/lvce-editor/editor-worker/pull/1632.

## Remaining cost

A large 75% reduction is not established by Basic Electron's different feature set. Further work should capture per-message payload sizes and serialization instruction samples around beforeinput, diagnostics, modified-tab notification and render forwarding, then test a single redundant message/batch against the same first-character protocol. Compare first-edit and steady typing explicitly; preloading or warm-up must not be represented as removing CPU work.

## Validation

The owner-repository PR and integration jobs passed on Ubuntu, macOS and Windows, including focused no-RPC/nonempty-RPC tests, typechecking, lint, existing editor/e2e and memory gates. The harness preserves hardware accounting, every one of six editor trials, and full-report validation. Release and published-artifact acceptance are recorded separately after completion.

## Shipped versions

The source change is in editor-worker 19.73.2, from successful release run
[38560799751](https://github.com/lvce-editor/editor-worker/actions/runs/38560799751).
LVCE integration [#15955](https://github.com/lvce-editor/lvce-editor/pull/15955)
merged with all four intended platform checks passed. Official LVCE v0.122.15
contains the new worker. The ARM64 Debian SHA256 is
`901fad5b4c8279be8af70120e55bfd873fd905a01695b4f3c863c29e493e4434`;
its manifest reports version 0.122.15 and architecture arm64, and its bundled
worker contains the early empty-line guard.

The full LVCE release passed in [run 38565764266](https://github.com/lvce-editor/lvce-editor/actions/runs/38565764266).
This repository's official-artifact matrix must also pass before completion. The released-artifact comparison measures all version-to-version
changes together; it does not assign their combined effect to this guard.
