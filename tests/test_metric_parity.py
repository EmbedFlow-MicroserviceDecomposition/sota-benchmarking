"""Parity with fyp-benchmarking's metrics.py and CHGNN's released metric.py.

tests/fixtures/parity holds a 14-class synthetic dataset; expected_fyp.json was produced by running
fyp-benchmarking's sm/icp/ifn/ned/ned_relative/ned_tripleboundt and CHGNN's get_IFN on the same data.
"""
import json
import shutil
from pathlib import Path

import pytest

from bcp.metric import evaluate_bcp
from chd.metric import evaluate_chd
from chm.metric import evaluate_chm
from ifn.metric import evaluate_ifn
from icp.metric import evaluate_icp
from ned.metric import evaluate_ned
from sm.metric import evaluate_sm

FIXTURE = Path(__file__).parent / "fixtures" / "parity"
EXPECTED = json.loads((FIXTURE / "expected_fyp.json").read_text())


@pytest.fixture()
def scored(tmp_path):
    out = tmp_path / "out"
    out.mkdir()
    shutil.copy(FIXTURE / "output.json", out)
    evaluate_sm(str(FIXTURE), str(out))
    evaluate_icp(str(FIXTURE), str(out))
    evaluate_ifn(str(FIXTURE), str(out))
    evaluate_ned(str(FIXTURE), str(out))
    evaluate_chm(str(FIXTURE), str(out))
    evaluate_chd(str(FIXTURE), str(out))
    evaluate_bcp(str(FIXTURE), str(out))
    return {n: json.loads((out / f"{n}_score.json").read_text()) for n in ("sm", "icp", "ifn", "ned", "chm", "chd", "bcp")}


def test_directed_sm_icp_and_ifn_match_fyp_canonical(scored):
    assert scored["sm"]["score"] == pytest.approx(EXPECTED["sm"], abs=1e-4)
    assert scored["icp"]["score"] == pytest.approx(EXPECTED["icp"], abs=1e-4)
    assert scored["ifn"]["score"] == pytest.approx(EXPECTED["ifn"], abs=1e-4)


def test_undirected_sm_matches_chgnn_repo_variant(scored):
    assert scored["sm"]["score_undirected"] == pytest.approx(EXPECTED["sm_undirected"], abs=1e-4)
    assert scored["sm"]["score_undirected"] == pytest.approx(EXPECTED["sm_chgnn_repo"], abs=1e-4)


def test_cross_edge_ifn_matches_chgnn_get_ifn(scored):
    assert scored["ifn"]["score_cross_edge"] == pytest.approx(EXPECTED["ifn_cross_edge"], abs=1e-4)


def test_ned_fixed_and_relative_match_fyp(scored):
    assert scored["ned"]["score"] == pytest.approx(EXPECTED["ned"], abs=1e-4)
    assert scored["ned"]["score_relative"] == pytest.approx(EXPECTED["ned_relative"], abs=1e-4)


def test_ned_triplebound_matches_fyp(scored):
    assert scored["ned"]["score_triplebound"] == pytest.approx(EXPECTED["ned_triplebound"], abs=1e-4)


def test_chm_chd_and_bcp_match_fyp(scored):
    assert scored["chm"]["score"] == pytest.approx(EXPECTED["chm"], abs=1e-4)
    assert scored["chd"]["score"] == pytest.approx(EXPECTED["chd"], abs=1e-4)
    assert scored["bcp"]["score"] == pytest.approx(EXPECTED["bcp"], abs=1e-4)
