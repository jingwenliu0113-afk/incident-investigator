"""Stability gate and run validity (decision 009 §3–4)."""

from collect.validity import container_metric_gaps, gate, period_observations

E504 = "/api/products/X | HTTPError('504 Server Error: Gateway Timeout for url: /api/products/X')"
ASK = "/prompt | gaierror(-2, 'Name or service not known')"


def st(ts, *, restarts=0, health="healthy", streak=0):
    return {"kind": "state", "ts": ts, "containers": {
        "checkout": {"restarts": restarts, "status": "running", "health": health, "streak": streak},
        "cart": {"restarts": 0, "status": "running", "health": None, "streak": None}}}


def lc(ts, errors):
    return {"kind": "locust", "ts": ts, "requests": 100, "failures": sum(errors.values()), "errors": errors}


def stable(minute0=0, minutes=6):
    """Samples every minute from 10:0<minute0> for `minutes` minutes, with warm-up 5xx before the gate window."""
    out = []
    for i in range(minutes + 1):
        ts = f"2026-10-08T10:{minute0 + i:02d}:00Z"
        out += [st(ts), lc(ts, {E504: 4, ASK: i})]
    return out


NOW = "2026-10-08T10:06:00Z"


def test_gate_passes_when_the_last_five_minutes_are_clean():
    g = gate(stable(), [], now=NOW)
    assert g["pass"] is True and all(g[k]["pass"] for k in ("G1", "G2", "G3"))


def test_gate_needs_five_minutes_of_samples():
    g = gate(stable(minute0=3, minutes=3), [], now=NOW)  # samples only since 10:03
    assert g["pass"] is False


def test_g1_any_restart_or_oom_since_up_fails_for_good():
    samples = stable()
    samples[-2] = st(NOW, restarts=1)
    assert gate(samples, [], now=NOW)["G1"]["pass"] is False
    oom = [{"ts": "2026-10-08T10:00:30Z", "service": "checkout", "action": "oom", "exit_code": None}]
    g = gate(stable(), oom, now=NOW)
    assert g["G1"]["pass"] is False and g["G1"].get("final") is True


def test_g2_unhealthy_or_failing_streak_in_window_fails():
    samples = stable()
    samples[6] = st("2026-10-08T10:03:00Z", streak=2)
    assert gate(samples, [], now=NOW)["G2"]["pass"] is False


def test_g3_new_5xx_in_window_fails_but_ambient_and_older_5xx_do_not():
    samples = stable()
    assert gate(samples, [], now=NOW)["G3"]["pass"] is True  # 4 warm-up 504s happened before the window
    samples[-1] = lc(NOW, {E504: 5, ASK: 9})
    assert gate(samples, [], now=NOW)["G3"]["pass"] is False


def test_period_observations_list_what_happened_between_two_times():
    samples = stable(minutes=10)
    samples[8] = st("2026-10-08T10:04:00Z", restarts=1)
    samples[10] = st("2026-10-08T10:05:00Z", restarts=1, streak=1)
    samples[-1] = lc("2026-10-08T10:10:00Z", {E504: 6, ASK: 10})
    events = [{"ts": "2026-10-08T10:04:30Z", "service": "checkout", "action": "die", "exit_code": 137},
              {"ts": "2026-10-08T10:09:30Z", "service": "email", "action": "oom", "exit_code": None}]
    obs = period_observations(samples, events, start="2026-10-08T10:02:00Z", end="2026-10-08T10:07:00Z")
    assert obs["clean"] is False
    assert obs["new_restarts"] == {"checkout": 1}
    assert obs["kills"] == ["10:04:30 checkout die exit=137"]  # the 10:09:30 OOM is outside the period
    assert obs["http_5xx"] == 0  # the 504s rose only after 10:07
    assert any("checkout" in h for h in obs["health"])
    clean = period_observations(stable(minutes=10), [], start="2026-10-08T10:02:00Z", end="2026-10-08T10:07:00Z")
    assert clean["clean"] is True


def test_container_metric_gaps_cover_every_full_minute_of_the_window():
    # decision 012: every SUT container needs docker_stats data in every full minute of the incident window
    minutes = {"cart": ["2026-10-08T10:01", "2026-10-08T10:02", "2026-10-08T10:03"],
               "shipping": ["2026-10-08T10:01", "2026-10-08T10:03"]}
    gaps = container_metric_gaps(minutes, services=["cart", "shipping", "quote"],
                                 start="2026-10-08T10:00:30Z", end="2026-10-08T10:03:40Z")
    assert gaps == {"shipping": ["10:02"], "quote": ["10:01", "10:02"]}  # 10:00 and 10:03 are partial minutes
    assert container_metric_gaps(minutes, services=["cart"], start="2026-10-08T10:01:00Z",
                                 end="2026-10-08T10:03:00Z") == {}
