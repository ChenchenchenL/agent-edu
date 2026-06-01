import pytest
import httpx

from agent_core.domain.entities.message import SessionMessage
from agent_core.domain.errors import ProviderError
from agent_core.infrastructure.llm.dashscope_compatible_provider import DashScopeCompatibleLLMProvider
from agent_core.infrastructure.llm.types import HintContext, SessionLearnerProfile


def make_provider() -> DashScopeCompatibleLLMProvider:
    return DashScopeCompatibleLLMProvider(
        api_key="secret",
        base_url="https://dashscope.aliyuncs.com/compatible-mode/v1",
        default_model="qwen3.5-flash",
        tutor_model="qwen3.5-flash",
        quiz_model="qwen3.5-flash",
        hint_model="qwen3.5-flash",
        timeout_seconds=30.0,
        max_retries=1,
        temperature=0.2,
        max_output_tokens=800,
    )


def make_message(role: str, content: str) -> SessionMessage:
    return SessionMessage.build(
        session_id="session-1",
        role=role,
        content=content,
        mode="chat" if role == "user" else "assistant",
        skill_trace=[] if role == "user" else ["explain_concept"],
    )


async def test_generate_tutor_reply_sends_history_and_latest_message(monkeypatch):
    provider = make_provider()
    captured: dict[str, object] = {}

    async def fake_post(self, url, *, headers, json):
        captured["url"] = url
        captured["headers"] = headers
        captured["payload"] = json
        request = httpx.Request("POST", f"{self.base_url}{url}")
        return httpx.Response(
            200,
            json={
                "choices": [
                    {
                        "message": {
                            "content": (
                                '{"definition":"Eigenvectors keep direction under a transform.",'
                                '"core_principles":["A matrix can scale some vectors without rotating them away from their line."],'
                                '"worked_example":"If Ax=2x, x is an eigenvector with eigenvalue 2.",'
                                '"common_mistake":"Confusing any output vector with an eigenvector.",'
                                '"next_step":"Check whether the transformed vector stays on the same line."}'
                            )
                        }
                    }
                ]
            },
            request=request,
        )

    monkeypatch.setattr(httpx.AsyncClient, "post", fake_post)

    reply = await provider.generate_tutor_reply(
        session_title="Linear Algebra",
        subject="Matrices",
        learner_message="Explain eigenvectors simply.",
        mode="chat",
        history=[
            make_message("user", "What is a matrix?"),
            make_message("assistant", "A matrix is a rectangular array of numbers."),
        ],
        memory_contexts=["learner previously confused matrix addition and multiplication"],
        learner_profile=SessionLearnerProfile(
            current_topic="Matrices",
            response_preference="explanatory",
            recent_struggles=["matrix addition vs multiplication"],
            known_context=["Session subject: Matrices"],
            long_term_context=["Earlier session on Matrices: learner struggled with determinants."],
            teaching_goal="explain and clarify",
            skill_directives=[],
        ),
    )

    assert reply.payload.type == "explanation"
    assert "Definition: Eigenvectors keep direction" in reply.content
    assert captured["url"] == "/chat/completions"
    payload = captured["payload"]
    assert isinstance(payload, dict)
    messages = payload["messages"]
    assert messages[0]["role"] == "system"
    assert "Session learner profile" in messages[1]["content"]
    assert "Long-term learner context" in messages[2]["content"]
    assert "Relevant memory retrieved" in messages[3]["content"]
    assert messages[4]["content"] == "What is a matrix?"
    assert messages[5]["content"] == "A matrix is a rectangular array of numbers."
    assert messages[6]["content"] == "Explain eigenvectors simply."


async def test_generate_hint_reply_includes_hint_context_and_safety(monkeypatch):
    provider = make_provider()
    captured: dict[str, object] = {}

    async def fake_post(self, url, *, headers, json):
        captured["payload"] = json
        request = httpx.Request("POST", f"{self.base_url}{url}")
        return httpx.Response(
            200,
            json={
                "choices": [
                    {
                        "message": {
                            "content": (
                                '{"hint_level":"targeted",'
                                '"next_step_hint":"Check what happens when you subtract 2 from both sides.",'
                                '"key_principle":"Undo addition with the inverse operation.",'
                                '"pitfall":"Do not stop after copying the original equation.",'
                                '"encouragement":"You only need one correction step.",'
                                '"direct_answer_given":false}'
                            )
                        }
                    }
                ]
            },
            request=request,
        )

    monkeypatch.setattr(httpx.AsyncClient, "post", fake_post)

    reply = await provider.generate_tutor_reply(
        session_title="Algebra",
        subject="Equations",
        learner_message="Give me a hint for solving x + 2 = 5.",
        mode="hint",
        history=[],
        memory_contexts=[],
        learner_profile=SessionLearnerProfile(
            current_topic="Equations",
            response_preference="guided",
            recent_struggles=["isolating the variable"],
            known_context=["Session subject: Equations"],
            long_term_context=[],
            teaching_goal="unblock next step",
            skill_directives=[],
        ),
        hint_context=HintContext(
            hint_level="targeted",
            question_prompt="Solve x + 2 = 5",
            learner_answer="x = 5",
            reference_answer="x = 3",
            prior_hint_count=1,
            mistake_analysis=["Learner answer does not align with the expected solution yet."],
        ),
    )

    assert reply.payload.type == "hint"
    assert reply.payload.hint_level == "targeted"
    assert reply.payload.direct_answer_given is False
    payload = captured["payload"]
    assert isinstance(payload, dict)
    messages = payload["messages"]
    assert "Hint adaptation context" in messages[2]["content"]
    assert "direct_answer_given must always be false" in messages[0]["content"]


async def test_generate_quiz_draft_parses_json_payload(monkeypatch):
    provider = make_provider()

    async def fake_post(self, url, *, headers, json):
        request = httpx.Request("POST", f"{self.base_url}{url}")
        return httpx.Response(
            200,
            json={
                "choices": [
                    {
                        "message": {
                            "content": (
                                '{"topic":"Matrices","difficulty":"easy","questions":['
                                '{"prompt":"What is a matrix?","answer":"A rectangular array of numbers."},'
                                '{"prompt":"What does a 2x2 matrix mean?","answer":"It has 2 rows and 2 columns."}'
                                "]}"
                            )
                        }
                    }
                ]
            },
            request=request,
        )

    monkeypatch.setattr(httpx.AsyncClient, "post", fake_post)

    quiz = await provider.generate_quiz_draft(
        topic="Matrices",
        difficulty="easy",
        question_count=2,
    )

    assert quiz.topic == "Matrices"
    assert quiz.difficulty == "easy"
    assert len(quiz.questions) == 2
    assert quiz.questions[0].prompt == "What is a matrix?"


async def test_generate_quiz_draft_rejects_wrong_question_count(monkeypatch):
    provider = make_provider()

    async def fake_post(self, url, *, headers, json):
        request = httpx.Request("POST", f"{self.base_url}{url}")
        return httpx.Response(
            200,
            json={
                "choices": [
                    {
                        "message": {
                            "content": (
                                '{"topic":"Matrices","difficulty":"easy","questions":['
                                '{"prompt":"Only one question","answer":"Only one answer"}'
                                "]}"
                            )
                        }
                    }
                ]
            },
            request=request,
        )

    monkeypatch.setattr(httpx.AsyncClient, "post", fake_post)

    with pytest.raises(ProviderError):
        await provider.generate_quiz_draft(
            topic="Matrices",
            difficulty="easy",
            question_count=2,
        )


async def test_generate_hint_reply_rejects_direct_answer(monkeypatch):
    provider = make_provider()

    async def fake_post(self, url, *, headers, json):
        request = httpx.Request("POST", f"{self.base_url}{url}")
        return httpx.Response(
            200,
            json={
                "choices": [
                    {
                        "message": {
                            "content": (
                                '{"hint_level":"targeted",'
                                '"next_step_hint":"The answer is x = 3.",'
                                '"key_principle":"Undo addition with subtraction.",'
                                '"pitfall":"Do not forget to isolate x.",'
                                '"encouragement":"You can do it.",'
                                '"direct_answer_given":true}'
                            )
                        }
                    }
                ]
            },
            request=request,
        )

    monkeypatch.setattr(httpx.AsyncClient, "post", fake_post)

    with pytest.raises(ProviderError):
        await provider.generate_tutor_reply(
            session_title="Algebra",
            subject="Equations",
            learner_message="Give me a hint for solving x + 2 = 5.",
            mode="hint",
            history=[],
            memory_contexts=[],
            learner_profile=SessionLearnerProfile(
                current_topic="Equations",
                response_preference="guided",
                recent_struggles=["isolating the variable"],
                known_context=["Session subject: Equations"],
                long_term_context=[],
                teaching_goal="unblock next step",
                skill_directives=[],
            ),
            hint_context=HintContext(
                hint_level="targeted",
                question_prompt="Solve x + 2 = 5",
                learner_answer="x = 5",
                reference_answer="x = 3",
                prior_hint_count=1,
                mistake_analysis=["Learner answer does not align with the expected solution yet."],
            ),
        )
