import pytest

from ethical_agent.install_progress import (
    PHASE_CONFIG,
    PHASE_MODEL,
    PHASE_OLLAMA,
    PHASE_PIP,
    PHASE_VENV,
    ProgressTracker,
    PullProgress,
    expected_model_bytes,
    format_bytes,
    plan_phases,
)
from ethical_agent.ollama_install import DEFAULT_LOCAL_MODEL

MODEL = DEFAULT_LOCAL_MODEL  # llama3.2:3b -- 2.0 GB in KNOWN_MODEL_SIZES


def _keys(**kwargs) -> list[str]:
    kwargs.setdefault("llm_mode", "local")
    kwargs.setdefault("model", MODEL)
    kwargs.setdefault("writes_config", False)
    return [phase.key for phase in plan_phases(**kwargs)]


# -- the phase plan --------------------------------------------------------


def test_plan_without_ollama_is_two_phases():
    assert _keys(want_llm=False) == [PHASE_VENV, PHASE_PIP]


def test_plan_without_ollama_gains_a_config_phase_when_there_is_a_password():
    # The audit password is written with or without a real model, so "gravar
    # configuração" is a real step there too -- and absent when there is
    # genuinely nothing to write.
    assert _keys(want_llm=False, writes_config=True) == [
        PHASE_VENV,
        PHASE_PIP,
        PHASE_CONFIG,
    ]


def test_plan_with_cloud_is_three_phases():
    assert _keys(want_llm=True, llm_mode="cloud") == [
        PHASE_VENV,
        PHASE_PIP,
        PHASE_CONFIG,
    ]


def test_plan_with_local_ollama_is_five_phases():
    assert _keys(want_llm=True, llm_mode="local") == [
        PHASE_VENV,
        PHASE_PIP,
        PHASE_OLLAMA,
        PHASE_MODEL,
        PHASE_CONFIG,
    ]


def test_weights_always_normalize_to_one_hundred():
    # The bar's denominator is fixed before it starts moving; a subset whose
    # weights don't add up would end somewhere other than the right edge.
    for kwargs in (
        dict(want_llm=False),
        dict(want_llm=False, writes_config=True),
        dict(want_llm=True, llm_mode="cloud"),
        dict(want_llm=True, llm_mode="local"),
    ):
        kwargs.setdefault("llm_mode", "local")
        kwargs.setdefault("writes_config", False)
        phases = plan_phases(model=MODEL, **kwargs)
        assert sum(phase.weight for phase in phases) == pytest.approx(100.0)


def test_model_phase_label_names_the_model():
    phases = plan_phases(
        want_llm=True, llm_mode="local", model="llama3.1:8b", writes_config=False
    )
    model_phase = next(p for p in phases if p.key == PHASE_MODEL)
    assert "llama3.1:8b" in model_phase.label


# -- the tracker -----------------------------------------------------------


def _local_tracker() -> ProgressTracker:
    return ProgressTracker(
        plan_phases(want_llm=True, llm_mode="local", model=MODEL, writes_config=False)
    )


def test_percent_never_decreases_even_when_a_fraction_goes_backwards():
    # A fresh `ollama pull` layer reports 0% after an earlier one reported
    # more; the bar must not rewind for it.
    tracker = _local_tracker()
    tracker.start(PHASE_MODEL)
    tracker.set_fraction(0.6)
    high = tracker.percent
    tracker.set_fraction(0.1)
    assert tracker.percent == high


def test_starting_a_phase_never_rewinds_past_what_finished():
    tracker = _local_tracker()
    tracker.start(PHASE_VENV)
    tracker.finish(PHASE_VENV)
    after_venv = tracker.percent
    tracker.start(PHASE_PIP)
    assert tracker.percent >= after_venv


def test_a_skipped_phase_still_moves_the_bar_to_its_end():
    # "Ollama já está instalado -- pulando" is progress, not a no-op.
    tracker = _local_tracker()
    tracker.start(PHASE_OLLAMA)
    started_at = tracker.percent
    tracker.finish(PHASE_OLLAMA)
    assert tracker.percent > started_at
    tracker.start(PHASE_MODEL)
    assert tracker.percent == started_at + tracker.phases[2].weight


def test_full_run_ends_at_one_hundred():
    tracker = _local_tracker()
    for phase in tracker.phases:
        tracker.start(phase.key)
        tracker.finish(phase.key)
    assert tracker.percent == 100.0


def test_unknown_phase_key_is_ignored_rather_than_shifting_the_bar():
    # ProgressPage marks PHASE_CONFIG unconditionally in some paths; when the
    # plan has no config phase that sentinel must do nothing at all.
    tracker = ProgressTracker(plan_phases(want_llm=False, llm_mode="local", model=MODEL, writes_config=False))
    tracker.start(PHASE_VENV)
    before = tracker.percent
    tracker.start(PHASE_CONFIG)
    tracker.finish(PHASE_CONFIG)
    assert tracker.percent == before


def test_fraction_before_any_phase_starts_is_ignored():
    tracker = _local_tracker()
    tracker.set_fraction(0.9)
    assert tracker.percent == 0.0


def test_label_names_the_step_and_counts_them():
    tracker = _local_tracker()
    tracker.start(PHASE_MODEL)
    assert "Etapa 4 de 5" in tracker.label
    assert MODEL in tracker.label


def test_label_carries_the_detail_while_it_is_set():
    tracker = _local_tracker()
    tracker.start(PHASE_MODEL)
    tracker.set_detail("1,2 GB de 2,0 GB")
    assert "1,2 GB de 2,0 GB" in tracker.label
    tracker.finish(PHASE_MODEL)
    assert "1,2 GB" not in tracker.label


def test_complete_reports_done():
    tracker = _local_tracker()
    tracker.start(PHASE_VENV)
    tracker.complete()
    assert tracker.percent == 100.0
    assert tracker.label == "Concluído."


# -- ollama pull output ----------------------------------------------------

# Captured shape of `ollama pull`, one entry per \r refresh, exactly as
# iter_stream_chunks yields them.
PULL_TRANSCRIPT = [
    "pulling manifest ",
    "pulling dde5aa3fc5ff:   0% ▕                ▏    0 B/2.0 GB                  ",
    "pulling dde5aa3fc5ff:   5% ▕█               ▏ 102 MB/2.0 GB   30 MB/s   1m3s ",
    "pulling dde5aa3fc5ff:  50% ▕████████        ▏ 1.0 GB/2.0 GB   30 MB/s     33s",
    "pulling dde5aa3fc5ff: 100% ▕████████████████▏ 2.0 GB                         ",
    "pulling 966de95ca8a6: 100% ▕████████████████▏ 1.4 KB                         ",
    "pulling fcc5a6bec9da: 100% ▕████████████████▏ 7.7 KB                         ",
    "verifying sha256 digest ",
    "writing manifest ",
    "success ",
]


def test_pull_progress_tracks_the_real_download():
    pull = PullProgress(MODEL)
    fractions = [f for f, _ in (pull.update(chunk) for chunk in PULL_TRANSCRIPT) if f is not None]
    assert fractions == sorted(fractions)  # monotonic
    assert fractions[0] == 0.0
    assert 0.04 < fractions[1] < 0.06  # 102 MB of 2.0 GB
    assert 0.49 < fractions[2] < 0.51  # 1.0 GB of 2.0 GB
    assert fractions[-1] >= 1.0


def test_lines_without_numbers_yield_nothing():
    pull = PullProgress(MODEL)
    for chunk in ("pulling manifest ", "verifying sha256 digest ", "success "):
        assert pull.update(chunk) == (None, None)


def test_a_tiny_layer_finishing_first_does_not_fill_the_bar():
    # The whole reason this sums bytes instead of reading the per-layer
    # percentage: a 7.7 KB config layer reaches 100% instantly, and a bar
    # following that number jumps to the end with 2 GB still to come.
    pull = PullProgress(MODEL)
    fraction, _ = pull.update("pulling fcc5a6bec9da: 100% ▕████▏ 7.7 KB")
    assert fraction is not None and fraction < 0.01
    fraction, _ = pull.update("pulling dde5aa3fc5ff:   1% ▕    ▏  20 MB/2.0 GB")
    assert fraction < 0.05


def test_transfer_speed_is_not_mistaken_for_a_size_pair():
    # "30 MB/s" has the same shape as "102 MB/2.0 GB" up to the unit.
    pull = PullProgress(MODEL)
    fraction, detail = pull.update(
        "pulling dde5aa3fc5ff:   5% ▕█  ▏ 102 MB/2.0 GB   30 MB/s   1m3s"
    )
    assert 0.04 < fraction < 0.06
    assert detail == "102,0 MB de 2,0 GB"


def test_a_layer_never_goes_backwards_within_the_sum():
    pull = PullProgress(MODEL)
    high, _ = pull.update("pulling dde5aa3fc5ff:  50% ▕███ ▏ 1.0 GB/2.0 GB")
    low, _ = pull.update("pulling dde5aa3fc5ff:  10% ▕█   ▏ 200 MB/2.0 GB")
    assert low == high


def test_unknown_model_reports_bytes_but_never_a_fraction():
    # No trustworthy denominator, so no percentage is invented -- the bar
    # degrades to phase-level progress while the label still shows real MB.
    pull = PullProgress("some-custom-model:latest")
    fraction, detail = pull.update("pulling dde5aa3fc5ff:  50% ▕███ ▏ 1.0 GB/2.0 GB")
    assert fraction is None
    assert detail == "1,0 GB de 2,0 GB"


def test_padding_width_does_not_break_the_percentage_match():
    # How wide ollama right-aligns that field is not a contract; the parser
    # must not be the thing that breaks when it changes.
    for chunk in (
        "pulling dde5aa3fc5ff:1% ▕▏ 20 MB/2.0 GB",
        "pulling dde5aa3fc5ff:      1% ▕▏ 20 MB/2.0 GB",
    ):
        fraction, _ = PullProgress(MODEL).update(chunk)
        assert fraction is not None


# -- formatting ------------------------------------------------------------


def test_format_bytes_uses_the_same_decimal_comma_as_the_options_screen():
    assert format_bytes(2 * 1000**3) == "2,0 GB"
    assert format_bytes(102 * 1000**2) == "102,0 MB"
    assert format_bytes(7700) == "7,7 KB"
    assert format_bytes(512) == "512 B"


def test_expected_model_bytes_never_guesses():
    assert expected_model_bytes(MODEL) == 2.0 * 1000**3
    assert expected_model_bytes("some-custom-model:latest") is None
