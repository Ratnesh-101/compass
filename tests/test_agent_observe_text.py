from backend.agent_observe_text import redact_internal_keys


def test_python_repr_user_id_removed():
    text = "{'count': 2, 'user_id': 'guest_abc', 'include_demo': False}"
    out = redact_internal_keys(text)
    assert "user_id" not in out and "guest_abc" not in out and "include_demo" not in out
    assert "'count': 2" in out


def test_json_user_id_removed_and_valid_json_remains():
    import json

    text = json.dumps({"user_id": "guest_abc", "owner": "x", "tasks": [1, 2]})
    out = redact_internal_keys(text)
    assert json.loads(out) == {"tasks": [1, 2]}


def test_plain_text_is_unchanged():
    assert redact_internal_keys("Found 3 task(s): a, b, c") == "Found 3 task(s): a, b, c"
