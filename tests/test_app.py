from streamlit.testing.v1 import AppTest

def test_app_runs_and_trades(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    import shutil, pathlib
    root = pathlib.Path(__file__).resolve().parents[1]
    at = AppTest.from_file(str(root / "app.py"), default_timeout=60)
    import sys; sys.path.insert(0, str(root))
    at.run()
    assert not at.exception, at.exception
    # advance replay 20 days
    [b for b in at.button if b.label == "+20"][0].click().run()
    assert at.session_state.cursor == 320
    # place a trade without reason -> rejected, with reason -> accepted
    [n for n in at.number_input if n.label == "Jumlah unit"][0].set_value(10).run()
    [b for b in at.button if b.label == "BELI"][0].click().run()
    assert any("alasan" in e.value for e in at.error)
    at.text_input[0].set_value("tes latihan").run()
    [b for b in at.button if b.label == "BELI"][0].click().run()
    assert not at.exception
    assert at.session_state.acct.holdings
