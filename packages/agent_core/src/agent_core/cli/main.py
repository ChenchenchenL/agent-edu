from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from dataclasses import asdict
from typing import Any

from agent_core.cli.client import BackendClient, create_embedded_client, create_remote_client
from agent_core.cli.config import CliConfig, load_cli_config, save_cli_config
from agent_core.cli.tui import AgentEduTui


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="agent-edu")
    parser.add_argument("--json", action="store_true", dest="json_output")
    parser.add_argument("--quiet", action="store_true")

    subparsers = parser.add_subparsers(dest="command", required=True)

    subparsers.add_parser("doctor")
    subparsers.add_parser("tui")

    profile = subparsers.add_parser("profile")
    profile_subparsers = profile.add_subparsers(dest="profile_command", required=True)
    profile_subparsers.add_parser("list")

    goal = subparsers.add_parser("goal")
    goal_subparsers = goal.add_subparsers(dest="goal_command", required=True)
    goal_list = goal_subparsers.add_parser("list")
    goal_list.add_argument("--profile-id")
    goal_jobs = goal_subparsers.add_parser("jobs")
    goal_jobs.add_argument("--goal-id")
    goal_materialize = goal_subparsers.add_parser("materialize-today")
    goal_materialize.add_argument("--goal-id")
    goal_select = goal_subparsers.add_parser("select")
    goal_select.add_argument("--goal-id", required=True)
    goal_select.add_argument("--profile-id")

    task = subparsers.add_parser("task")
    task_subparsers = task.add_subparsers(dest="task_command", required=True)
    task_today = task_subparsers.add_parser("today")
    task_today.add_argument("--goal-id")
    task_execute = task_subparsers.add_parser("execute")
    task_execute.add_argument("task_id")
    task_status = task_subparsers.add_parser("status")
    task_status.add_argument("task_id")
    task_status.add_argument("status")
    task_status.add_argument("--result-note")

    session = subparsers.add_parser("session")
    session_subparsers = session.add_subparsers(dest="session_command", required=True)
    session_subparsers.add_parser("resume")

    memory = subparsers.add_parser("memory")
    memory_subparsers = memory.add_subparsers(dest="memory_command", required=True)
    memory_search = memory_subparsers.add_parser("search")
    memory_search.add_argument("--type", choices=["knowledge", "behavior"], default="knowledge")
    memory_search.add_argument("--profile-id")
    memory_search.add_argument("--query", required=True)
    memory_search.add_argument("--goal-id")
    memory_browse = memory_subparsers.add_parser("browse")
    memory_browse.add_argument("--type", choices=["knowledge", "behavior"], default="knowledge")
    memory_browse.add_argument("--profile-id")
    memory_browse.add_argument("--goal-id")
    memory_browse.add_argument("--status", action="append")
    memory_browse.add_argument("--limit", type=int, default=20)
    memory_browse.add_argument("--offset", type=int, default=0)

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    config = load_cli_config()
    if args.command == "tui":
        return _run_tui(config)
    return asyncio.run(_run_command(args, config))


async def _run_command(args: argparse.Namespace, config: CliConfig) -> int:
    client = _build_client(config)
    try:
        if args.command == "doctor":
            report = await client.doctor(
                active_profile_id=config.active_profile_id,
                active_goal_id=config.active_goal_id,
            )
            return _emit(args, asdict(report))

        if args.command == "profile" and args.profile_command == "list":
            profiles = [item.model_dump(mode="json") for item in await client.list_profiles()]
            return _emit(args, profiles)

        if args.command == "goal" and args.goal_command == "list":
            profile_id = args.profile_id or config.active_profile_id
            if profile_id is None:
                raise SystemExit("No active profile selected.")
            goals = [item.model_dump(mode="json") for item in await client.list_goals(profile_id)]
            return _emit(args, goals)

        if args.command == "goal" and args.goal_command == "jobs":
            goal_id = args.goal_id or config.active_goal_id
            if goal_id is None:
                raise SystemExit("No active goal selected.")
            jobs = [item.model_dump(mode="json") for item in await client.list_autonomy_jobs(goal_id)]
            return _emit(args, jobs)

        if args.command == "goal" and args.goal_command == "materialize-today":
            goal_id = args.goal_id or config.active_goal_id
            if goal_id is None:
                raise SystemExit("No active goal selected.")
            state = await client.materialize_today(goal_id)
            return _emit(args, state.model_dump(mode="json"))

        if args.command == "goal" and args.goal_command == "select":
            profile_id = args.profile_id or config.active_profile_id
            if profile_id is None:
                profiles = await client.list_profiles()
                if not profiles:
                    raise SystemExit("No learner profiles available.")
                profile_id = profiles[0].id
            goals = await client.list_goals(profile_id)
            selected = next((item for item in goals if item.id == args.goal_id), None)
            if selected is None:
                raise SystemExit(f"Goal not found in profile '{profile_id}'.")
            config.active_profile_id = profile_id
            config.active_goal_id = selected.id
            save_cli_config(config)
            return _emit(args, {"active_profile_id": profile_id, "active_goal_id": selected.id})

        if args.command == "task" and args.task_command == "today":
            goal_id = args.goal_id or config.active_goal_id
            if goal_id is None:
                raise SystemExit("No active goal selected.")
            workspace = await client.get_workspace(config.active_profile_id or "", goal_id)
            tasks = [item.model_dump(mode="json") for item in workspace.today_tasks]
            return _emit(args, tasks)

        if args.command == "task" and args.task_command == "execute":
            result = await client.execute_task(args.task_id)
            config.last_task_id = result.task.id
            config.last_session_id = result.execution_session_id
            save_cli_config(config)
            return _emit(args, result.model_dump(mode="json"))

        if args.command == "task" and args.task_command == "status":
            result = await client.update_task_status(
                args.task_id,
                status=args.status,
                result_note=args.result_note,
            )
            return _emit(args, result.model_dump(mode="json"))

        if args.command == "session" and args.session_command == "resume":
            profile_id = config.active_profile_id
            if profile_id is None:
                raise SystemExit("No active profile selected.")
            workspace = await client.get_workspace(profile_id, config.active_goal_id)
            sessions = [item.model_dump(mode="json") for item in workspace.recent_sessions]
            return _emit(args, sessions)

        if args.command == "memory" and args.memory_command == "search":
            profile_id = args.profile_id or config.active_profile_id
            if profile_id is None:
                raise SystemExit("No active profile selected.")
            if args.type == "knowledge":
                result = await client.retrieve_knowledge_memories(
                    learner_profile_id=profile_id,
                    query_text=args.query,
                )
            else:
                result = await client.retrieve_behavior_memories(
                    learner_profile_id=profile_id,
                    query_text=args.query,
                )
            return _emit(args, result.model_dump(mode="json"))

        if args.command == "memory" and args.memory_command == "browse":
            profile_id = args.profile_id or config.active_profile_id
            if profile_id is None:
                raise SystemExit("No active profile selected.")
            if args.type == "knowledge":
                result = await client.browse_knowledge_memories(
                    learner_profile_id=profile_id,
                    learner_goal_id=args.goal_id or config.active_goal_id,
                    statuses=args.status,
                    limit=args.limit,
                    offset=args.offset,
                )
            else:
                result = await client.browse_behavior_memories(
                    learner_profile_id=profile_id,
                    learner_goal_id=args.goal_id or config.active_goal_id,
                    statuses=args.status,
                    limit=args.limit,
                    offset=args.offset,
                )
            return _emit(args, result.model_dump(mode="json"))
    finally:
        await client.close()
    return 0


def _run_tui(config: CliConfig) -> int:
    client = _build_client(config)
    try:
        app = AgentEduTui(client=client, config=config)
        app.run()
        return 0
    finally:
        asyncio.run(client.close())


def _build_client(config: CliConfig) -> BackendClient:
    operator_api_key = os.environ.get("AGENT_EDU_OPERATOR_API_KEY")
    if config.mode == "embedded":
        return create_embedded_client(
            operator_api_key=operator_api_key,
            learner_access_key=config.learner_access_key,
        )
    return create_remote_client(
        config.api_base_url,
        operator_api_key=operator_api_key,
        learner_access_key=config.learner_access_key,
    )


def _emit(args: argparse.Namespace, payload: Any) -> int:
    if args.json_output:
        print(json.dumps(payload, ensure_ascii=False, indent=None if args.quiet else 2))
        return 0
    if isinstance(payload, list):
        for item in payload:
            print(_format_item(item))
        return 0
    if isinstance(payload, dict):
        if args.quiet:
            print(payload)
            return 0
        print(json.dumps(payload, ensure_ascii=False, indent=2))
        return 0
    print(payload)
    return 0


def _format_item(item: Any) -> str:
    if isinstance(item, dict):
        return ", ".join(f"{key}={value}" for key, value in item.items())
    return str(item)


if __name__ == "__main__":
    sys.exit(main())
