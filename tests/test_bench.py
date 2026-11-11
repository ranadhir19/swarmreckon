from swarmreckon.bench import run_bench, write_bench_outputs
from swarmreckon.providers import FakeProvider
from swarmreckon.samples import SAMPLES


def test_bench_mechanics_with_fake_provider(tmp_path):
    results = run_bench(lambda: FakeProvider(), repeats=1,
                        root=tmp_path, log=lambda *a: None)
    assert len(results["runs"]) == len(SAMPLES) * 2  # tasks x modes
    assert all("check_score" in r for r in results["runs"])
    for task in SAMPLES:
        per_mode = results["summary"][task.id]
        assert per_mode["sequential"]["runs_ok"] == 1
        assert per_mode["parallel"]["runs_ok"] == 1
        assert per_mode["speedup_parallel_vs_sequential"] is not None


def test_bench_outputs_written(tmp_path):
    results = run_bench(lambda: FakeProvider(), repeats=1,
                        root=tmp_path / "work", log=lambda *a: None)
    json_path, md_path = write_bench_outputs(results, tmp_path / "out")
    assert json_path.exists() and md_path.exists()
    assert "speedup" in md_path.read_text()
