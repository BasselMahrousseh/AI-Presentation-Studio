import pytest

from utils.dict_utils import (
    deep_update,
    has_more_than_n_keys,
)


def test_has_more_than_n_keys():
    assert has_more_than_n_keys({"a": 1, "b": 2}, n=1) is True
    assert has_more_than_n_keys({"a": 1}, n=1) is False


@pytest.mark.parametrize(
    ("original", "updates", "expected"),
    [
        ({"a": {"x": 1}}, {"a": {"y": 2}}, {"a": {"x": 1, "y": 2}}),
        ({"a": [1, 2]}, {"a": []}, {"a": [1, 2]}),
        ({"a": [{"k": 1}]}, {"a": [{"k": 2}]}, {"a": [{"k": 2}]}),
        ({"a": [1, 2]}, {"a": [9, 8, 7]}, {"a": [9, 8]}),
        ({"a": 1}, {"a": 2}, {"a": 2}),
        ({}, {"b": 3}, {"b": 3}),
        ({"nested": {}}, {}, {"nested": {}}),
    ],
)
def test_deep_update_modes(original: dict, updates: dict, expected: dict):
    assert deep_update(original, updates) == expected


def test_deep_update_deeply_nested_lists_of_dicts():
    original = {"slides": [{"a": {"x": 1}}, {"b": 2}]}
    updates = {"slides": [{"a": {"x": 2}}, {"b": 3}]}
    assert deep_update(original, updates) == {"slides": [{"a": {"x": 2}}, {"b": 3}]}


def test_deep_update_single_dict_into_list_slot_with_scalar_original():
    assert deep_update({"a": [99]}, {"a": [{"k": True}]}) == {"a": [{"k": True}]}


