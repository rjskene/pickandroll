"""A cleared held player's activation, chosen on the queue's own score (#360, the user's ruling on
Q1): the week plan's score when a plan leads, else the three weeks. 224319 on 2026-11-10: the
comeback dropped the day's add (a streamer the plan kept to 11-13) because he had the lowest
per-game value. The season guard and the keep rule hold. Nothing here opens a page.
"""

from __future__ import annotations

import json
from dataclasses import replace

from pickandroll.api import season_moves
from pickandroll.season import Player
from pickandroll.season import moves as mv
from tests.test_moves import WEEKS, build, player, rates, streaming_league
from tests.test_season import LEAGUE, NOW, client  # noqa: F401 - the fixture

BACK = 5
STREAMER = 10
WEAK = 3
LATER = WEEKS[0][4]


def league(**kw):
    """The streaming league with the streamer already mine (the day's add), his per-game value
    the lowest, and player 5 cleared on IL: his activation must drop someone."""
    roster, cands, rate, sched, opponent, field = streaming_league()
    roster = [*roster, player(STREAMER, "STR")]
    cands = [c for c in cands if c[0] != STREAMER]
    rate |= {BACK: rates(1.0)}
    value = {k: 1.0 for k in rate} | {1: 1.2, WEAK: 0.4, STREAMER: 0.2}
    held = [(BACK, Player(BACK, "Back", "MIN", ("C",), status="P"))]
    return build(
        roster,
        cands,
        rate,
        sched,
        opponent,
        field,
        held=held,
        held_slots={BACK: "IL"},
        value=value,
        **kw,
    )


PLAN = [mv.Move(11, STREAMER, LATER)]
SCORE = season_moves.plan_value(0.33, False)


def test_the_old_rule_drops_the_streamer_the_plan_keeps():
    p = league()
    [c] = mv.comebacks(p, "week", ())
    assert (c.player, c.drop) == (BACK, STREAMER)  # the lowest per-game value


def test_the_activation_on_the_plans_score_keeps_the_streamer_to_his_step():
    p = league()
    chosen = mv.choose_activation(p, SCORE, None, PLAN)
    assert chosen == {BACK: WEAK}
    # The comebacks, the evaluator and the plans then send the chosen drop.
    q = replace(p, activation=chosen)
    assert [(c.player, c.drop) for c in mv.comebacks(q, "week", PLAN)] == [(BACK, WEAK)]
    # Dropping the streamer now costs his games before the step and the step itself.
    ev = mv.Evaluator(q)
    dropped = mv.Evaluator(replace(p, activation={BACK: STREAMER}))
    assert SCORE(ev, PLAN) > SCORE(dropped, [])


def test_a_drop_the_keep_rule_keeps_is_never_chosen_and_all_kept_choose_nothing():
    p = replace(league(), kept=frozenset({WEAK}))
    assert mv.choose_activation(p, SCORE, None, PLAN)[BACK] != WEAK
    everyone = replace(league(), kept=frozenset({1, 2, WEAK, STREAMER, BACK}))
    assert mv.choose_activation(everyone, SCORE, None, PLAN) == {}


def test_a_pending_claims_add_is_never_the_activation_drop_chosen_or_fallen_back_to():
    # A claim's add is on the folded roster from his clear day but not mine before Yahoo's run.
    for add in (WEAK, STREAMER):
        p = replace(league(), pending=frozenset({add}))
        assert mv.choose_activation(p, SCORE, None, PLAN)[BACK] != add
    # The fallback skips him although his per-game value is the lowest, and so does a choice
    # that names him.
    p = replace(league(), pending=frozenset({STREAMER}))
    assert [c.drop for c in mv.comebacks(p, "week", ())] != [STREAMER]
    named = replace(p, activation={BACK: STREAMER})
    assert [c.drop for c in mv.comebacks(named, "week", ())] != [STREAMER]


def test_the_season_guard_refuses_a_drop_worth_more_than_him_and_falls_back_to_the_season_best():
    p = league()
    # 3 is worth more than 5 over the season: refused although the plan's score likes him.
    worth = {WEAK: -1.0, STREAMER: 0.5, 1: -2.0, 2: -2.0}
    chosen = mv.choose_activation(p, SCORE, lambda k, d: worth[d], PLAN)
    assert chosen[BACK] != WEAK
    # He is kept himself and every other drop is refused: the season-best of them goes.
    kept = replace(p, kept=frozenset({BACK}))
    refused = {WEAK: -1.0, STREAMER: -3.0, 1: -2.0, 2: -0.5}
    assert mv.choose_activation(kept, SCORE, lambda k, d: refused[d], PLAN) == {BACK: 2}


def test_the_queue_takes_the_plans_steps_when_a_plan_leads_else_the_three_weeks():
    built = season_moves.Built(problem=league(), system={}, horizons={}, adds={}, unprojected=0)
    step = {"add": 11, "drop": STREAMER, "from": LATER.isoformat()}
    led = {"week_plans": {"queue": 0, "plans": [{"steps": [step]}]}}
    moves, objective, by = season_moves.queue_moves(built, led)
    assert moves == PLAN and by == "week_plan"
    ev = mv.Evaluator(built.problem)
    assert objective(ev, moves) == ev.value("week", moves) + 0.33 * ev.value("three", moves)
    three = {"week_plans": {"queue": None}, "recommended": {"three": {"moves": [step]}}}
    moves, objective, by = season_moves.queue_moves(built, three)
    assert by == "three" and objective is season_moves.three_value


def test_the_solve_chooses_again_on_the_queues_score_and_solves_once_more(monkeypatch):
    built = season_moves.Built(problem=league(), system={}, horizons={}, adds={}, unprojected=0)
    solved = []

    def payload(b, budget=None):
        solved.append(dict(b.problem.activation))
        step = {"add": 11, "drop": STREAMER, "from": LATER.isoformat()}
        return {"week_plans": {"queue": 0, "plans": [{"steps": [step]}]}}

    monkeypatch.setattr(season_moves, "moves_payload", payload)
    first = season_moves.with_activation(built, {BACK: STREAMER})
    again, out = season_moves.solve(first)
    assert solved == [{BACK: STREAMER}, {BACK: WEAK}]  # chosen again, solved once more
    assert again.problem.activation == {BACK: WEAK}
    assert out["activation"] == {"by": "week_plan", "drops": [{"player": BACK, "drop": WEAK}]}
    # Chosen the same: solved once.
    solved.clear()
    season_moves.solve(again)
    assert solved == [{BACK: WEAK}]


def test_the_comeback_takes_the_logged_activation_while_it_still_holds():
    built = season_moves.Built(problem=league(), system={}, horizons={}, adds={}, unprojected=0)
    got = season_moves.logged_activation(built, {BACK: WEAK})
    assert got.as_read.activation == {BACK: WEAK}
    assert [(c.player, c.drop) for c in mv.comebacks(got.as_read, "week", ())] == [(BACK, WEAK)]
    # A drop no longer on the roster, or a player no longer cleared, keeps the build's own.
    assert season_moves.logged_activation(built, {BACK: 77}) is built
    assert season_moves.logged_activation(built, {6: WEAK}) is built


def test_the_days_activation_is_read_from_the_decision_log_after_a_restart(client):  # noqa: F811
    svc = client.app.state.seasons
    today = NOW.date()
    folder = client.data_dir / "leagues" / LEAGUE / "season" / "decisions"
    folder.mkdir(parents=True, exist_ok=True)
    act = {"by": "week_plan", "drops": [{"player": 6406, "drop": 7}]}
    entries = [{"at": "x", "activation": None}, {"at": "y", "activation": act}, {"at": "z"}]
    (folder / f"{today.isoformat()}.json").write_text(json.dumps(entries))
    assert svc._day_activation(LEAGUE, today) == {6406: 7}
