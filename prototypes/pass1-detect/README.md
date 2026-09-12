# PROTOTYPE — pass 1 (issue #11)

Throwaway. Run it, look at the output, throw it away. The decision it settles belongs in
an ADR, not here.

    python3 prototypes/pass1-detect/pass1.py <video-id>          # reads the fixture cache
    python3 prototypes/pass1-detect/pass1.py path/to/video.mp4

Writes `out/spike-pass1/<id>/slides/*.jpg` plus an `index.html` review page (each image
linked to its second in the YouTube video).

## What it does

Looks at the video twice a second, at 480 px wide. Compares each sample with the last
screen it considered still, counting how much of the **drawing** changed (auto-Canny off
the luma median, dilated, mean absolute difference). When a screen has held still long
enough, it saves it. It always saves the first frame, always flushes the pending screen at
EOF, and never goes longer than the watchdog interval without saving something.

Six knobs, all on the command line: `--fps --width --thresh --dwell --watchdog --dupe`.

## Run over the sweep fixtures (45m55, 2026-09-12)

| fixture | class | kept | dwell | watchdog | dupes dropped | time |
|---|---|---|---|---|---|---|
| `pJc0l2DASpo` | C1+C3 | 38 | 34 | 2 | 14 | 10 s |
| `jqpdveK2XAU` | C2b | 19 | 13 | 4 | 27 | 9 s |
| `b9dBJnQ_kpo` | C2b unstable | 31 | 15 | 14 | 20 | 32 s |
| `2AWv_nIfp-U` | C4 | 53 | 49 | 2 | 33 | 38 s |
| `YBH8rQv4aTQ` | C5 | 78 | 37 | 39 | 3 | 45 s |
| `X3uFwLj2u7Q` | C7 | 22 | 1 | 20 | 12 | 31 s |

241 images, 109 duplicates dropped, 2 min 45 s of wall clock for 45m55 of video.
