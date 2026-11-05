from lyra.market import leaderboard as L


def act(last_hour=10, day=30, week=168, outlets=10):
    return {"last_hour": last_hour, "day": day, "week": week, "outlets": outlets}


def test_noise_cant_top_the_board():
    rows = L.build({"AAA": act(last_hour=2, day=2, week=2, outlets=2), "BBB": act(last_hour=1, day=3, outlets=1)}, {}, {}, {})
    assert [r["ticker"] for r in rows] == ["BBB"]


def test_score_stays_in_range_and_rises_with_each_signal():
    quiet = L.move_score(act(last_hour=1, outlets=1), None)
    busy = L.move_score(act(last_hour=50), None)
    stressed = L.move_score(act(last_hour=50), {"stress": 90, "change_24h": 25})
    full = L.move_score(act(last_hour=500, outlets=500), {"stress": 100, "change_24h": 90}, trades=9, catalysts=2)
    assert 0 <= quiet < busy < stressed <= full == 100


def test_velocity_compares_with_the_usual_hour():
    assert L.velocity(act(last_hour=10, week=168)) == 10
    assert L.velocity(act(last_hour=1, week=0)) == 4


def test_reason_names_real_signals():
    line = L.reason(act(last_hour=48), {"change_24h": 12}, 0, -0.6)
    assert line == "Insider selling + Tremor up 12 in 24 h + 48 stories in 1h"
    assert L.reason(act(last_hour=0, day=5), None, 0, None) == "5 stories in 24h"


def test_rank_changes_new_entries_and_jumps():
    first = L.build({t: act(last_hour=n) for t, n in (("A", 9), ("B", 6), ("C", 4), ("D", 2))}, {}, {}, {})
    assert not any(r["new"] for r in first)
    second = L.build({t: act(last_hour=n) for t, n in (("D", 9.5), ("A", 9), ("B", 6), ("E", 3))}, {}, {}, {}, previous=first)
    by = {r["ticker"]: r for r in second}
    assert by["D"]["change"] == 3 and by["D"]["jump"]
    assert by["A"]["change"] == -1 and not by["A"]["jump"]
    assert by["E"]["new"]


def test_ten_rows_at_most():
    rows = L.build({f"T{i}": act(last_hour=i + 1) for i in range(15)}, {}, {}, {})
    assert len(rows) == 10 and [r["rank"] for r in rows] == list(range(1, 11))
