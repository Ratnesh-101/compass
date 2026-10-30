"""query_coursework_tasks must not report 0 tasks just because the agent passed a label nothing matches."""
import pytest

from backend.skills.handlers.tasks import handle_query_coursework_tasks

TASKS = [
    {"id": 1, "title": "DBMS assignment 3", "domain": "coursework", "status": "open", "due_date": "2026-10-31", "priority": "medium"},
    {"id": 2, "title": "Theory of Computation quiz prep", "domain": "coursework", "status": "open", "due_date": "2026-11-01", "priority": "medium"},
]


class _Acquire:
    async def __aenter__(self):
        return object()

    async def __aexit__(self, *exc):
        return False


class _Pool:
    def acquire(self):
        return _Acquire()


@pytest.fixture(autouse=True)
def _tasks(monkeypatch):
    async def fake_list_chat_tasks(conn, args, **filters):
        return list(TASKS)

    monkeypatch.setattr("backend.skills.handlers.tasks.list_chat_tasks", fake_list_chat_tasks)


@pytest.mark.asyncio
@pytest.mark.parametrize("label", ["coursework", "all", "my courses", "CS 999"])
async def test_unmatched_course_label_falls_back_to_all_coursework_tasks(label):
    result = await handle_query_coursework_tasks({"course": label, "status": "open", "user_id": "u1"}, _Pool())

    assert "DBMS assignment 3" in result["response"]
    assert "Theory of Computation quiz prep" in result["response"]


@pytest.mark.asyncio
async def test_matching_course_label_still_narrows_the_list():
    result = await handle_query_coursework_tasks({"course": "dbms", "status": "open", "user_id": "u1"}, _Pool())

    assert "DBMS assignment 3" in result["response"]
    assert "Theory of Computation quiz prep" not in result["response"]


@pytest.mark.asyncio
async def test_no_course_label_lists_everything():
    result = await handle_query_coursework_tasks({"status": "open", "user_id": "u1"}, _Pool())

    assert "DBMS assignment 3" in result["response"]
    assert "Theory of Computation quiz prep" in result["response"]
