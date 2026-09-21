from pickandroll.projections import validate, zscores
from pickandroll.sources.bbm import is_per_game, load_bbm_export, normalize_bbm, read_bbm_export


def test_totals_export_normalizes(bbm_totals_path):
    raw = read_bbm_export(bbm_totals_path)
    assert not is_per_game(raw)
    df = normalize_bbm(raw)
    validate(df)
    assert len(df) == len(raw)
    assert df.index.is_unique
    assert (df["fgm"] <= df["fga"]).all()
    assert "bbm_z_pts" in df.columns and "yahoo_owned_pct" in df.columns


def test_per_game_export_becomes_totals(bbm_pergame_path):
    raw = read_bbm_export(bbm_pergame_path)
    assert is_per_game(raw)
    df = normalize_bbm(raw)
    validate(df)
    row = raw.iloc[0]
    pid = df.index[0]
    assert abs(df.loc[pid, "pts"] - row["p/g"] * row["g"]) < 1e-6
    assert abs(df.loc[pid, "minutes"] - row["m/g"] * row["g"]) < 1e-6


def test_load_projection_set_and_zscores_match_bbm_direction(bbm_totals_path):
    ps = load_bbm_export(bbm_totals_path, horizon="season")
    assert ps.source == "bbm" and ps.horizon == "season"
    z = zscores(ps.df, pool_size=156)
    # Our z-scores should broadly agree with Basketball Monster's own value columns.
    corr = z["pts"].corr(ps.df["bbm_z_pts"])
    assert corr > 0.95
    corr_tov = z["tov"].corr(ps.df["bbm_z_tov"])
    assert corr_tov > 0.95
