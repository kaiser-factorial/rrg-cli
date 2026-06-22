import json
import threading
from pathlib import Path
from urllib.request import urlopen

from rrg_cli.gui import make_handler, status
from rrg_cli.scorecard import build_scorecard


def test_scorecard_is_provisional_and_versioned(ready_project):
    run = ready_project.root / "operator/robustness_TestModel"
    raw = run / "raw"
    raw.mkdir(parents=True)
    key = ready_project.root / "operator/origin"
    for question in range(1, 4):
        (raw / f"Q{question}_summary.json").write_text(json.dumps({"estimate": question / 10}))
        (key / f"Q{question}.md").write_text(f"## Q{question}\nHeld-back finding {question}")
    first = build_scorecard(ready_project, run, "robustness", "TestModel")
    second = build_scorecard(ready_project, run, "robustness", "TestModel")
    text = Path(first["path"]).read_text()
    assert first["version"] == 1 and second["version"] == 2
    assert first["final_verdicts"] == 0
    assert text.count("**PENDING**") == 3
    assert "Held-back finding" in text


def test_gui_status_and_http_endpoint(ready_project):
    from http.server import ThreadingHTTPServer

    payload = status(ready_project)
    assert payload["project"] == "starter-validation"
    assert [stage["id"] for stage in payload["stages"]] == ["replication", "robustness", "generalization"]
    server = ThreadingHTTPServer(("127.0.0.1", 0), make_handler(ready_project))
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        with urlopen(f"http://127.0.0.1:{server.server_port}/api/status") as response:
            data = json.loads(response.read())
        assert data["preflight"]["ok"]
    finally:
        server.shutdown()
        server.server_close()
