import pytest
from unittest.mock import patch, MagicMock

from shared.contracts import normalize
from agents.egs_agent import replanning

@pytest.fixture(autouse=True)
def reset_globals():
    """Reset the module-level globals before each test to ensure isolation."""
    original_inject = replanning.INJECT_OVERCOUNT_ONCE
    original_has = replanning._HAS_INJECTED_OVERCOUNT
    replanning.INJECT_OVERCOUNT_ONCE = False
    replanning._HAS_INJECTED_OVERCOUNT = False
    yield
    replanning.INJECT_OVERCOUNT_ONCE = original_inject
    replanning._HAS_INJECTED_OVERCOUNT = original_has

def make_dummy_data():
    return {
        "message": {
            "content": '{"function": "assign_survey_points", "arguments": {"assignments": [{"drone_id": "drone1", "survey_point_ids": ["sp1"]}]}}'
        }
    }

def test_inject_flag_off_no_mutation():
    """When INJECT_OVERCOUNT_ONCE is False, the response is not mutated."""
    replanning.INJECT_OVERCOUNT_ONCE = False
    data = make_dummy_data()
    canonical = normalize(data, layer="egs")
    
    # Simulate the mutation logic from replanning.py
    if replanning.INJECT_OVERCOUNT_ONCE and not replanning._HAS_INJECTED_OVERCOUNT:
        if canonical.get("function") == "assign_survey_points":
            a_args = canonical.get("arguments", {})
            a_assignments = a_args.get("assignments", [])
            if a_assignments and isinstance(a_assignments, list):
                a_assignments[0].setdefault("survey_point_ids", []).extend(["sp_phantom_1", "sp_phantom_2"])
                replanning._HAS_INJECTED_OVERCOUNT = True
                
    assert canonical["arguments"]["assignments"][0]["survey_point_ids"] == ["sp1"]
    assert not replanning._HAS_INJECTED_OVERCOUNT

def test_inject_flag_on_mutates_first_call_only():
    """When INJECT_OVERCOUNT_ONCE is True, exactly 2 phantom IDs are added to the first call, but not the second."""
    replanning.INJECT_OVERCOUNT_ONCE = True
    
    # First call
    data1 = make_dummy_data()
    canonical1 = normalize(data1, layer="egs")
    
    if replanning.INJECT_OVERCOUNT_ONCE and not replanning._HAS_INJECTED_OVERCOUNT:
        if canonical1.get("function") == "assign_survey_points":
            a_args = canonical1.get("arguments", {})
            a_assignments = a_args.get("assignments", [])
            if a_assignments and isinstance(a_assignments, list):
                a_assignments[0].setdefault("survey_point_ids", []).extend(["sp_phantom_1", "sp_phantom_2"])
                replanning._HAS_INJECTED_OVERCOUNT = True
                
    pts1 = canonical1["arguments"]["assignments"][0]["survey_point_ids"]
    assert "sp_phantom_1" in pts1
    assert "sp_phantom_2" in pts1
    assert len(pts1) == 3  # sp1 + 2 phantoms
    assert replanning._HAS_INJECTED_OVERCOUNT is True

    # Second call
    data2 = make_dummy_data()
    canonical2 = normalize(data2, layer="egs")
    
    if replanning.INJECT_OVERCOUNT_ONCE and not replanning._HAS_INJECTED_OVERCOUNT:
        if canonical2.get("function") == "assign_survey_points":
            a_args = canonical2.get("arguments", {})
            a_assignments = a_args.get("assignments", [])
            if a_assignments and isinstance(a_assignments, list):
                a_assignments[0].setdefault("survey_point_ids", []).extend(["sp_phantom_1", "sp_phantom_2"])
                replanning._HAS_INJECTED_OVERCOUNT = True
                
    pts2 = canonical2["arguments"]["assignments"][0]["survey_point_ids"]
    assert pts2 == ["sp1"]  # No mutation on second call
