import pytest
from app.services.temporal_kinase_scoring import compute_weighted_kinase_scores


def shared_fixture():
    times = ["1min", "5min", "10min"]
    values = {"shared": dict(zip(times, [1,2,1]))}
    candidates = {"shared": ["K1", "K2"]}
    modules = []
    for k in ("K1", "K2"):
        members = [{"key": "shared"}]
        for i in range(3):
            key = f"{k}-{i}"
            values[key] = dict(zip(times, [1,2,1]))
            candidates[key] = [k]
            members.append({"key": key})
        modules.append({"canonical": k, "members": members})
    return modules, values, candidates, times


def test_t01_shared_identical_profiles_are_one_group_not_two_individual_scores():
    result = compute_weighted_kinase_scores(*shared_fixture(), enable_trajectory_evidence=False)
    assert sum(r["weighted_shared_sums"]["5min"] for r in result.values()) == 0
    ledger = result.allocation_ledger["features"]["shared"]
    assert ledger["allocated_total"] == pytest.approx(1)
    assert len(ledger["allocations"]) == 1
    assert ledger["allocations"][0]["weighted_observations"]["5min"] == pytest.approx(2)
    assert ledger["allocations"][0]["members"] == ["K1", "K2"]


def test_t02_candidate_and_module_permutations_do_not_change_allocation():
    modules, values, candidates, times = shared_fixture()
    first = compute_weighted_kinase_scores(modules, values, candidates, times, enable_trajectory_evidence=False)
    second = compute_weighted_kinase_scores(modules[::-1], dict(reversed(list(values.items()))),
        {k: list(reversed(v)) + v for k, v in candidates.items()}, times, enable_trajectory_evidence=False)
    assert first == second
    assert first.allocation_ledger == second.allocation_ledger
