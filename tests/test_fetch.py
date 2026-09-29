"""`fetch URL`: the first slice an operator uses, through seam 1.

The acquirer is the fake from `conftest.py`, so nothing here downloads. What
is asserted is what the output directory holds afterwards and what the run
said while making it.
"""

import json
from pathlib import Path

import json3
from extract_slides.cli import app

URL = "https://youtu.be/jqpdveK2XAU"


def run_directory(root: Path) -> Path:
    (directory,) = [path for path in (root / "out").iterdir() if path.is_dir()]
    return directory


def test_fetch_leaves_the_video_in_a_directory_named_for_the_talk(cli, tmp_path):
    cli.invoke(app, ["fetch", URL])

    directory = tmp_path / "out" / "containers-from-scratch-devconf-2024-jqpdveK2XAU"
    assert (directory / "source.mp4").is_file()


def test_an_asr_caption_becomes_a_transcript_that_keeps_each_word_timing(cli, acquirer, tmp_path):
    acquirer.automatic = {
        "en-orig": json3.track(
            json3.window(40_000),
            json3.spoken(1_000, 4_000, [(0, "hello"), (500, "and"), (900, "welcome")]),
            json3.scroll(4_990),
        )
    }

    result = cli.invoke(app, ["fetch", URL])

    assert result.exit_code == 0, result.output
    transcript = json.loads((run_directory(tmp_path) / "transcript.json").read_text())
    assert transcript["origin"] == "asr-caption"
    assert transcript["fidelity"] == "word"
    assert transcript["cues"] == [
        {
            "start": 1.0,
            "end": 5.0,
            "text": "hello and welcome",
            "words": [
                {"start": 1.0, "end": 1.5, "text": "hello"},
                {"start": 1.5, "end": 1.9, "text": "and"},
                {"start": 1.9, "end": 5.0, "text": "welcome"},
            ],
        }
    ]


def test_the_raw_caption_stays_beside_the_transcript(cli, acquirer, tmp_path):
    cli.invoke(app, ["fetch", URL])

    raw = run_directory(tmp_path) / "caption.asr.en-orig.json3"
    assert raw.read_text() == acquirer.automatic["en-orig"]


def transcript_of(tmp_path: Path) -> dict:
    return json.loads((run_directory(tmp_path) / "transcript.json").read_text())


def test_the_whole_video_window_and_the_scroll_markers_carry_no_speech(cli, acquirer, tmp_path):
    acquirer.automatic = {
        "en-orig": json3.track(
            json3.window(40_000),
            json3.spoken(0, 2_000, [(0, "first")]),
            json3.scroll(1_990),
            json3.spoken(2_000, 2_000, [(0, "second")]),
            json3.scroll(3_990),
        )
    }

    cli.invoke(app, ["fetch", URL])

    assert [cue["text"] for cue in transcript_of(tmp_path)["cues"]] == ["first", "second"]


def test_an_event_with_no_duration_ends_where_the_next_speech_starts(cli, acquirer, tmp_path):
    acquirer.automatic = {
        "en-orig": json3.track(
            json3.spoken(1_000, None, [(0, "no"), (400, "duration")]),
            json3.spoken(3_000, 1_000, [(0, "after")]),
        )
    }

    result = cli.invoke(app, ["fetch", URL])

    assert result.exit_code == 0, result.output
    first = transcript_of(tmp_path)["cues"][0]
    assert (first["start"], first["end"]) == (1.0, 3.0)
    assert first["words"][-1] == {"start": 1.4, "end": 3.0, "text": "duration"}


def test_the_last_event_with_no_duration_ends_at_its_last_word(cli, acquirer, tmp_path):
    acquirer.automatic = {
        "en-orig": json3.track(json3.spoken(1_000, None, [(0, "the"), (600, "end")]))
    }

    cli.invoke(app, ["fetch", URL])

    last = transcript_of(tmp_path)["cues"][-1]
    assert (last["start"], last["end"]) == (1.0, 1.6)


def test_a_human_caption_loses_its_leading_credits_and_keeps_its_speech(cli, acquirer, tmp_path):
    acquirer.subtitles = {
        "en": json3.human_track(
            [
                (0.0, 4.0, "Transcriber: Ana Souza"),
                (4.0, 6.0, "Reviewer: Bruno Lima"),
                (7.0, 10.0, "Good afternoon, everyone."),
                (10.0, 12.0, "Reviewer: that is what I am today."),
            ]
        )
    }

    result = cli.invoke(app, ["fetch", URL])

    assert result.exit_code == 0, result.output
    transcript = transcript_of(tmp_path)
    assert transcript["origin"] == "human-caption"
    assert transcript["fidelity"] == "cue", "a human caption carries no word timings"
    assert transcript["cues"] == [
        {"start": 7.0, "end": 10.0, "text": "Good afternoon, everyone.", "words": []},
        {"start": 10.0, "end": 12.0, "text": "Reviewer: that is what I am today.", "words": []},
    ], "only the credits that open the track are metadata; the speech after them is kept whole"


#: The one fixture worth versioning, because it is text (#24): the ASR original
#: of `jqpdveK2XAU`, a 4 min 16 s reference talk, as `yt-dlp` saved it.
REAL_CAPTION = Path(__file__).parent / "fixtures" / "captions" / "jqpdveK2XAU.en-orig.json3"


def test_the_parser_loses_no_speech_from_a_real_caption(cli, acquirer, tmp_path):
    """Total speech coverage, the recall rule applied to the parser.

    The pairing's "every cue appears in exactly one slide" only proves nothing
    is lost after this point; a cue the parser drops never reaches it. The
    expected words are read the naive way — every segment's text, in order —
    which is the whole of YouTube's definition of what a track says.
    """
    raw = REAL_CAPTION.read_text(encoding="utf-8")
    acquirer.duration = 256.3
    acquirer.automatic = {"en-orig": raw}

    result = cli.invoke(app, ["fetch", URL])

    assert result.exit_code == 0, result.output
    said = "".join(
        seg.get("utf8", "") for event in json.loads(raw)["events"] for seg in event.get("segs", [])
    ).split()
    cues = transcript_of(tmp_path)["cues"]
    assert " ".join(cue["text"] for cue in cues).split() == said
    assert " ".join(word["text"] for cue in cues for word in cue["words"]).split() == said


# --- the caption that belongs to another talk --------------------------------


def lightning_talk(acquirer, *, human_ends_at: float, asr: bool) -> None:
    """ADR 0007's measured case: a 300 s talk whose human caption runs on."""
    acquirer.duration = 300.0
    acquirer.subtitles = {
        "en": json3.human_track([(1.0, 290.0, "my talk"), (293.0, human_ends_at, "the next talk")])
    }
    acquirer.automatic = (
        {"en-orig": json3.asr_track(300.0, [(1.0, 299.0, "my talk as heard")])} if asr else {}
    )


def test_a_caption_running_past_the_video_is_rejected_for_the_next_one(cli, acquirer, tmp_path):
    lightning_talk(acquirer, human_ends_at=676.0, asr=True)

    result = cli.invoke(app, ["fetch", URL])

    assert result.exit_code == 0, result.output
    assert transcript_of(tmp_path)["origin"] == "asr-caption"
    assert "676.0 s" in result.stdout and "300.0 s" in result.stdout, "the reason is reported"


def test_with_no_caption_left_the_run_says_why_and_stops(cli, acquirer, tmp_path):
    lightning_talk(acquirer, human_ends_at=676.0, asr=False)

    result = cli.invoke(app, ["fetch", URL, "--report", "json"])

    assert result.exit_code == 2
    assert "676.0 s" in result.stderr, "the rejection is reported, not just the stop"
    document = json.loads(result.stdout)
    assert document["error"] == "not_implemented"
    assert "local transcription" in document["message"].lower()
    assert not (run_directory(tmp_path) / "transcript.json").exists()


def test_the_overrun_tolerance_is_two_seconds_past_the_end(cli, acquirer, tmp_path):
    lightning_talk(acquirer, human_ends_at=301.99, asr=False)

    assert cli.invoke(app, ["fetch", URL]).exit_code == 0


def test_just_past_the_tolerance_is_rejected(cli, acquirer, tmp_path):
    lightning_talk(acquirer, human_ends_at=302.01, asr=False)

    assert cli.invoke(app, ["fetch", URL]).exit_code == 2


# --- which tracks are requested -----------------------------------------------

SPEECH = json3.asr_track(40.0, [(0.0, 10.0, "something said")])


def test_a_machine_translated_track_is_never_requested(cli, acquirer):
    # One real ASR track and its machine translations, as YouTube lists them:
    # the bare "en" is the same track again, and the rest are translations.
    acquirer.automatic = {key: SPEECH for key in ["en-orig", "en", "de", "es", "pt", "ja"]}

    cli.invoke(app, ["fetch", URL])

    assert acquirer.requested == ["en-orig"]


def test_the_audio_language_chooses_the_tracks(cli, acquirer, tmp_path):
    acquirer.language = "pt"
    acquirer.subtitles = {"en": SPEECH, "pt-BR": SPEECH}
    acquirer.automatic = {"pt-orig": SPEECH, "en": SPEECH}

    cli.invoke(app, ["fetch", URL])

    assert acquirer.requested == ["pt-BR", "pt-orig"], "human first, then the ASR original"
    assert transcript_of(tmp_path)["source"] == "caption.human.pt-BR.json3"


def test_a_live_chat_replay_is_not_a_caption(cli, acquirer):
    acquirer.subtitles = {"live_chat": SPEECH}

    cli.invoke(app, ["fetch", URL])

    assert acquirer.requested == ["en-orig"]


def test_a_single_original_track_names_the_language_the_source_did_not(cli, acquirer):
    acquirer.language = None
    acquirer.automatic = {"pt-orig": SPEECH, "en": SPEECH}

    cli.invoke(app, ["fetch", URL])

    assert acquirer.requested == ["pt-orig"]


def test_with_no_language_to_choose_by_nothing_is_requested_and_the_run_says_so(cli, acquirer):
    acquirer.language = None
    acquirer.subtitles = {"en": SPEECH}
    acquirer.automatic = {"en-orig": SPEECH, "fr-orig": SPEECH}

    result = cli.invoke(app, ["fetch", URL])

    assert acquirer.requested == []
    assert result.exit_code == 2
    assert "no audio language" in result.stdout


# --- when the downloader fails -------------------------------------------------


def test_a_download_failure_names_the_downloader_and_the_fix(cli, acquirer):
    acquirer.failure = "HTTP Error 403: Forbidden"

    result = cli.invoke(app, ["fetch", URL, "--report", "json"])

    assert result.exit_code == 2
    document = json.loads(result.stdout)
    assert document["error"] == "download_failed"
    assert "yt-dlp" in document["message"], "the operator is told which program failed"
    assert "self-update --yt-dlp" in document["hint"]
    assert "self-update --yt-dlp" in result.stderr


def test_a_download_failing_mid_run_is_named_the_same_way(cli, acquirer, output_directory):
    directory = output_directory()
    acquirer.failure = "HTTP Error 403: Forbidden"

    result = cli.invoke(app, [str(directory), "--force", "--report", "json"])

    assert result.exit_code == 2
    assert json.loads(result.stdout)["error"] == "download_failed"


# --- the run, as the output directory records it -------------------------------


def manifest_of(tmp_path: Path) -> dict:
    return json.loads((run_directory(tmp_path) / "manifest.json").read_text())


def test_fetching_again_resumes_rather_than_downloading_again(cli, acquirer):
    cli.invoke(app, ["fetch", URL])

    result = cli.invoke(app, ["fetch", URL])

    assert result.exit_code == 0, result.output
    assert acquirer.media_downloads == 1
    assert result.stdout.count("reused") == 2
    assert "--force" in result.stdout


def test_a_title_edited_since_the_last_run_still_finds_that_run(cli, acquirer, tmp_path):
    cli.invoke(app, ["fetch", URL])
    acquirer.title = "Containers From Scratch (updated)"

    result = cli.invoke(app, ["fetch", URL])

    assert acquirer.media_downloads == 1, "the video id identifies the talk, not its title"
    assert len(list((tmp_path / "out").iterdir())) == 1
    assert result.stdout.count("reused") == 2


def test_force_fetches_again(cli, acquirer):
    cli.invoke(app, ["fetch", URL])

    cli.invoke(app, ["fetch", URL, "--force"])

    assert acquirer.media_downloads == 2


def test_the_run_header_records_where_the_transcript_came_from(cli, tmp_path):
    cli.invoke(app, ["fetch", URL])

    run = manifest_of(tmp_path)["run"]
    assert run["video_id"] == "jqpdveK2XAU"
    assert run["url"] == URL
    assert run["transcript_origin"] == "asr-caption"
    assert run["transcript_fidelity"] == "word"
    assert run["stt_model"] is None
    assert set(run["stages"]) == {"acquire", "transcribe"}


def test_the_media_file_not_the_platform_is_the_authority_on_duration(cli, acquirer, tmp_path):
    # The platform rounds to the second; the file on disk does not. A caption
    # that fits the real media by a hair must not be judged against the rounding.
    acquirer.duration = 256.0
    acquirer.media_duration = 256.3
    acquirer.automatic = {"en-orig": json3.asr_track(256.0, [(250.0, 258.2, "thank you")])}

    result = cli.invoke(app, ["fetch", URL])

    assert result.exit_code == 0, result.output
    assert manifest_of(tmp_path)["run"]["duration"] == 256.3
    assert transcript_of(tmp_path)["duration"] == 256.3


def test_the_prose_transcript_reads_every_cue_in_order_with_no_timestamps(cli, acquirer, tmp_path):
    acquirer.automatic = {
        "en-orig": json3.asr_track(
            40.0, [(0.0, 5.0, "hello and welcome"), (5.0, 9.0, "to the talk"), (9.0, 12.0, "at 10:30")]
        )
    }

    cli.invoke(app, ["fetch", URL])

    prose = (run_directory(tmp_path) / "transcript.md").read_text()
    assert prose.split() == "hello and welcome to the talk at 10:30".split()


def test_a_long_prose_transcript_is_broken_into_paragraphs(cli, acquirer, tmp_path):
    sentence = "this is one sentence of a long talk."
    acquirer.automatic = {
        "en-orig": json3.asr_track(40.0, [(i * 0.1, i * 0.1 + 0.1, sentence) for i in range(60)])
    }

    cli.invoke(app, ["fetch", URL])

    paragraphs = (run_directory(tmp_path) / "transcript.md").read_text().strip().split("\n\n")
    assert len(paragraphs) > 1
    assert all(paragraph.strip() for paragraph in paragraphs)


def test_out_says_where_the_directory_is_created(cli, tmp_path):
    cli.invoke(app, ["fetch", URL, "--out", "talks"])

    (directory,) = (tmp_path / "talks").iterdir()
    assert directory.name.endswith("-jqpdveK2XAU")


def test_a_local_video_file_is_refused_by_name_rather_than_misreported(cli, tmp_path):
    (tmp_path / "talk.mp4").write_bytes(b"a local file")

    result = cli.invoke(app, ["fetch", "talk.mp4", "--report", "json"])

    assert result.exit_code == 2
    document = json.loads(result.stdout)
    assert document["error"] == "not_implemented", "not a downloader failure"
    assert "local video file" in document["message"].lower()


# --- found in review ---------------------------------------------------------


def test_a_source_that_states_no_duration_is_reported_not_a_traceback(cli, acquirer):
    acquirer.duration = 0.0

    result = cli.invoke(app, ["fetch", URL, "--report", "json"])

    assert result.exit_code == 2
    assert result.exception is None or isinstance(result.exception, SystemExit)
    assert json.loads(result.stdout)["error"] == "no_duration"


def test_fetching_again_forgets_the_stages_built_on_the_old_download(
    cli, acquirer, output_directory, tmp_path
):
    directory = output_directory("out/a-talk-jqpdveK2XAU")

    result = cli.invoke(app, ["fetch", URL, "--force"])

    assert result.exit_code == 0, result.output
    stages = json.loads((directory / "manifest.json").read_text())["run"]["stages"]
    assert set(stages) == {"acquire", "transcribe"}, (
        "detection, crop and pairing described the old video and must run again"
    )


def test_a_transcribe_that_fails_leaves_no_old_transcript_standing(
    cli, acquirer, output_directory
):
    directory = output_directory("out/a-talk-jqpdveK2XAU")
    lightning_talk(acquirer, human_ends_at=676.0, asr=False)

    result = cli.invoke(app, ["fetch", URL, "--force"])

    assert result.exit_code == 2
    stages = json.loads((directory / "manifest.json").read_text())["run"]["stages"]
    assert "transcribe" not in stages
    assert not (directory / "transcript.json").exists()
    assert not (directory / "transcript.md").exists()


def test_the_downloader_reason_is_printed_verbatim_brackets_and_all(cli, acquirer):
    # yt-dlp prefixes its reasons with the extractor in brackets, which the
    # terminal library would otherwise read as a formatting tag and swallow.
    acquirer.failure = "[youtube] jqpdveK2XAU: Sign in to confirm you're not a bot"

    result = cli.invoke(app, ["fetch", URL])

    assert "[youtube] jqpdveK2XAU" in result.stderr
