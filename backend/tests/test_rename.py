"""Data and settings left by the app's former name ("Home Trainer", before 2026-11)."""

from opengpx_trainer import storage as st
from opengpx_trainer.envvars import env
from opengpx_trainer.storage import Storage


def test_new_variable_wins_over_the_former_one(monkeypatch):
    monkeypatch.delenv("OPENGPX_TRAINER_ANT_LOG", raising=False)
    monkeypatch.setenv("HOMETRAINER_ANT_LOG", "/old.csv")
    assert env("ANT_LOG") == "/old.csv"
    monkeypatch.setenv("OPENGPX_TRAINER_ANT_LOG", "/new.csv")
    assert env("ANT_LOG") == "/new.csv"
    monkeypatch.delenv("HOMETRAINER_ANT_LOG")
    monkeypatch.setenv("OPENGPX_TRAINER_ANT_LOG", "")
    assert env("ANT_LOG") is None


def test_former_data_directory_is_moved_once(tmp_path, monkeypatch):
    monkeypatch.delenv("OPENGPX_TRAINER_DATA", raising=False)
    monkeypatch.delenv("HOMETRAINER_DATA", raising=False)
    (tmp_path / ".hometrainer" / "rides").mkdir(parents=True)
    (tmp_path / ".hometrainer" / "rides" / "a.fit").write_bytes(b"fit")

    d = st.default_data_dir(tmp_path)
    assert d == tmp_path / ".opengpx-trainer"
    assert (d / "rides" / "a.fit").read_bytes() == b"fit"
    assert not (tmp_path / ".hometrainer").exists()

    # a former directory appearing again later is left alone: the new one already exists
    (tmp_path / ".hometrainer").mkdir()
    assert st.default_data_dir(tmp_path) == d
    assert (tmp_path / ".hometrainer").exists()


def test_data_variable_skips_the_move(tmp_path, monkeypatch):
    (tmp_path / ".hometrainer").mkdir()
    monkeypatch.setenv("HOMETRAINER_DATA", str(tmp_path / "custom"))
    assert st.default_data_dir(tmp_path) == tmp_path / "custom"
    assert (tmp_path / ".hometrainer").exists()


def test_former_database_is_renamed_and_fit_paths_follow(tmp_path):
    old_dir, new_dir = tmp_path / ".hometrainer", tmp_path / ".opengpx-trainer"
    s = Storage(old_dir)
    old_fit = s.rides_dir / "ride.fit"
    old_fit.write_bytes(b"fit")
    rid = s.add_ride(
        started_at="2026-11-01T10:00:00",
        mode="erg",
        name="Old ride",
        summary={},
        fit_path=str(old_fit),
    )
    s.close()
    (old_dir / "opengpx-trainer.db").rename(old_dir / "hometrainer.db")  # as before the rename
    old_dir.rename(new_dir)

    s = Storage(new_dir)
    assert not (new_dir / "hometrainer.db").exists()
    ride = s.get_ride(rid)
    assert ride["name"] == "Old ride"
    assert ride["fit_path"] == str(new_dir / "rides" / "ride.fit")
    s.close()
