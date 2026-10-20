from __future__ import annotations

import time

import pytest

from app.progress import AutoScrollingStatus, run_with_heartbeat


class FakeStatus:
    def __init__(self) -> None:
        self.messages: list[str] = []
        self.html_blocks: list[tuple[str, bool]] = []
        self.updates: list[dict] = []

    def write(self, message: str) -> None:
        self.messages.append(message)

    def html(self, body: str, *, unsafe_allow_javascript: bool) -> None:
        self.html_blocks.append((body, unsafe_allow_javascript))

    def update(self, **kwargs) -> None:
        self.updates.append(kwargs)


def test_run_with_heartbeat_reports_operation_and_waiting_progress() -> None:
    messages: list[str] = []

    def operation(report):
        report("Responses API · request sent.")
        time.sleep(0.03)
        report("MCP approval · response returned.")
        return "complete"

    result = run_with_heartbeat(
        operation,
        messages.append,
        waiting_message="waiting for approval",
        heartbeat_seconds=0.01,
        poll_seconds=0.002,
    )

    assert result == "complete"
    assert messages[0] == "Responses API · request sent."
    assert any(message.startswith("Still working") for message in messages)
    assert messages[-1] == "MCP approval · response returned."


def test_run_with_heartbeat_reraises_worker_error() -> None:
    def operation(_report):
        raise RuntimeError("approval failed")

    with pytest.raises(RuntimeError, match="approval failed"):
        run_with_heartbeat(
            operation,
            lambda _message: None,
            waiting_message="waiting",
            heartbeat_seconds=0.01,
            poll_seconds=0.002,
        )


def test_auto_scrolling_status_follows_each_message_but_not_completion() -> None:
    status = FakeStatus()
    progress = AutoScrollingStatus(status)

    progress.write("Responses API · request sent.")
    progress.write("MCP · get_catalog completed.")
    progress.update(label="Review complete", state="complete", expanded=False)

    assert status.messages == [
        "Responses API · request sent.",
        "MCP · get_catalog completed.",
    ]
    assert len(status.html_blocks) == 2
    assert all(unsafe for _, unsafe in status.html_blocks)
    assert all("scrollIntoView" in body for body, _ in status.html_blocks)
    assert status.html_blocks[0][0] != status.html_blocks[1][0]
    assert status.updates == [
        {"label": "Review complete", "state": "complete", "expanded": False}
    ]
