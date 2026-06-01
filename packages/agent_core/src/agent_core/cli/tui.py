from __future__ import annotations

from dataclasses import dataclass

from textual.app import App, ComposeResult
from textual.containers import Horizontal
from textual.widgets import Footer, Header, Input, RichLog, Static

from agent_core.cli.client import BackendClient
from agent_core.cli.config import CliConfig, save_cli_config
from agent_core.domain.schemas.planning import DailyTaskResponse
from agent_core.domain.schemas.session import MessageRequest
from agent_core.domain.schemas.workspace import WorkspaceSummaryResponse


@dataclass
class TaskSelection:
    task: DailyTaskResponse
    label: str


class AgentEduTui(App[None]):
    BINDINGS = [
        ("ctrl+r", "refresh", "Refresh"),
        ("ctrl+c", "quit", "Quit"),
    ]

    CSS = """
    Screen {
        layout: vertical;
    }
    #body {
        height: 1fr;
    }
    #left, #right {
        width: 32;
        padding: 1;
        border: solid $primary;
    }
    #center {
        width: 1fr;
        border: solid $primary;
    }
    #log {
        height: 1fr;
    }
    #command {
        dock: bottom;
    }
    """

    def __init__(self, *, client: BackendClient, config: CliConfig) -> None:
        super().__init__()
        self._client = client
        self._config = config
        self._workspace: WorkspaceSummaryResponse | None = None
        self._current_task: DailyTaskResponse | None = None
        self._current_session_id: str | None = config.last_session_id

    def compose(self) -> ComposeResult:
        yield Header(show_clock=True)
        with Horizontal(id="body"):
            yield Static("Loading workspace...", id="left")
            yield RichLog(id="log", highlight=True, wrap=True, markup=False)
            yield Static("Memory panel", id="right")
        yield Input(placeholder="Type a question or /refresh /task 1 /done /skip /hint", id="command")
        yield Footer()

    def on_mount(self) -> None:
        self.run_worker(self._load_workspace(), exclusive=True)

    async def action_refresh(self) -> None:
        await self._load_workspace()

    async def on_input_submitted(self, event: Input.Submitted) -> None:
        value = event.value.strip()
        event.input.value = ""
        if not value:
            return
        if value.startswith("/"):
            await self._handle_command(value)
            return
        await self._send_message(content=value, mode="chat")

    async def _handle_command(self, raw_command: str) -> None:
        log = self.query_one("#log", RichLog)
        parts = raw_command.split(maxsplit=1)
        command = parts[0]
        arg = parts[1] if len(parts) > 1 else ""
        if command == "/refresh":
            await self._load_workspace()
            return
        if command == "/today":
            self._render_workspace()
            return
        if command == "/task":
            await self._select_task(arg)
            return
        if command == "/done":
            await self._update_current_task("completed")
            return
        if command == "/skip":
            await self._update_current_task("skipped")
            return
        if command == "/hint":
            if not arg:
                arg = "Give me the next hint."
            await self._send_message(content=arg, mode="hint")
            return
        if command == "/session":
            await self._select_session(arg)
            return
        if command == "/memory":
            self._render_memory_panel(query=arg or None)
            return
        log.write(f"Unknown command: {raw_command}")

    async def _load_workspace(self) -> None:
        if self._config.active_profile_id is None:
            profiles = await self._client.list_profiles()
            if not profiles:
                self.query_one("#left", Static).update("No learner profiles yet. Create one via API or CLI.")
                return
            self._config.active_profile_id = profiles[0].id
            save_cli_config(self._config)
        self._workspace = await self._client.get_workspace(
            self._config.active_profile_id,
            self._config.active_goal_id,
        )
        if self._workspace.learner_goal is not None:
            self._config.active_goal_id = self._workspace.learner_goal.id
            save_cli_config(self._config)
        self._render_workspace()
        if self._current_session_id is not None:
            await self._load_history(self._current_session_id)

    def _render_workspace(self) -> None:
        left = self.query_one("#left", Static)
        right = self.query_one("#right", Static)
        if self._workspace is None:
            left.update("Workspace unavailable.")
            right.update("Memory unavailable.")
            return
        goal = self._workspace.learner_goal
        lines = [
            "agent-edu",
            f"Profile: {self._workspace.learner_profile.id}",
            f"Goal: {goal.title if goal is not None else 'none'}",
            f"Plan: v{self._workspace.active_plan.version if self._workspace.active_plan is not None else '-'}",
            "",
            "Today tasks:",
        ]
        for index, task in enumerate(self._workspace.today_tasks, start=1):
            marker = "*" if self._current_task is not None and task.id == self._current_task.id else " "
            lines.append(f"{marker}{index}. {task.title} [{task.status}]")
        if not self._workspace.today_tasks:
            lines.append("  none")
        lines.append("")
        lines.append("Review:")
        for task in self._workspace.review_tasks[:5]:
            lines.append(f"- {task.title} [{task.status}]")
        if not self._workspace.review_tasks:
            lines.append("  none")
        left.update("\n".join(lines))
        memory_panel = self._build_memory_panel(query=None)
        workflow_lines = ["", "Recent workflows:"]
        for item in self._workspace.recent_workflow_runs:
            workflow_lines.append(f"- {item.workflow_type} [{item.status}]")
        right.update(memory_panel + "\n" + "\n".join(workflow_lines))

    def _render_memory_panel(self, query: str | None) -> None:
        right = self.query_one("#right", Static)
        right.update(self._build_memory_panel(query=query))

    def _build_memory_panel(self, query: str | None) -> str:
        if self._workspace is None:
            return "Memory unavailable."
        lines = [
            "Long-term memory",
            f"Knowledge: {self._workspace.memory_summary.knowledge_count}",
            f"Behavior: {self._workspace.memory_summary.behavior_count}",
            "",
            "Knowledge:",
        ]
        for item in self._workspace.memory_summary.knowledge_items[:5]:
            if query and query.lower() not in item.title.lower() and query.lower() not in item.summary.lower():
                continue
            lines.append(f"- {item.title} [{item.status}]")
        lines.append("")
        lines.append("Behavior:")
        for item in self._workspace.memory_summary.behavior_items[:5]:
            if query and query.lower() not in item.title.lower() and query.lower() not in item.summary.lower():
                continue
            lines.append(f"- {item.title} [{item.status}]")
        return "\n".join(lines)

    async def _select_task(self, task_index: str) -> None:
        log = self.query_one("#log", RichLog)
        if self._workspace is None:
            log.write("Workspace not loaded.")
            return
        try:
            index = int(task_index.strip()) - 1
        except ValueError:
            log.write("Usage: /task <number>")
            return
        tasks = self._workspace.today_tasks
        if index < 0 or index >= len(tasks):
            log.write("Task index out of range.")
            return
        self._current_task = tasks[index]
        execution = await self._client.execute_task(self._current_task.id)
        self._current_task = execution.task
        self._current_session_id = execution.execution_session_id
        self._config.last_task_id = self._current_task.id
        self._config.last_session_id = self._current_session_id
        save_cli_config(self._config)
        log.write(f"Selected task: {self._current_task.title}")
        await self._load_history(self._current_session_id)
        await self._load_workspace()

    async def _select_session(self, session_id: str) -> None:
        log = self.query_one("#log", RichLog)
        if not session_id:
            if self._workspace is None or not self._workspace.recent_sessions:
                log.write("No recent sessions.")
                return
            session_id = self._workspace.recent_sessions[0].id
        self._current_session_id = session_id.strip()
        self._config.last_session_id = self._current_session_id
        save_cli_config(self._config)
        await self._load_history(self._current_session_id)

    async def _send_message(self, *, content: str, mode: str) -> None:
        log = self.query_one("#log", RichLog)
        if self._current_session_id is None:
            if self._config.last_task_id is not None:
                await self._select_task("1")
            else:
                log.write("No active session. Select a task with /task <number> first.")
                return
        response = await self._client.create_message(
            self._current_session_id or "",
            MessageRequest(content=content, mode=mode),
        )
        log.write(f"You: {content}")
        log.write(f"Assistant: {response.assistant_message}")
        await self._load_workspace()

    async def _update_current_task(self, status: str) -> None:
        log = self.query_one("#log", RichLog)
        if self._current_task is None:
            log.write("No selected task.")
            return
        self._current_task = await self._client.update_task_status(self._current_task.id, status=status, result_note=None)
        log.write(f"Task updated: {self._current_task.title} -> {self._current_task.status}")
        await self._load_workspace()

    async def _load_history(self, session_id: str) -> None:
        log = self.query_one("#log", RichLog)
        history = await self._client.get_message_history(session_id, limit=20)
        log.clear()
        for item in history.items:
            prefix = "You" if item.role == "user" else "Assistant"
            log.write(f"{prefix}: {item.content}")
