import json

import pytest
from conftest import ScriptedProvider

from evog.app import Application
from evog.benchmark_data import Episode, load_corpus, load_episodes
from evog.benchmark_judge import parse_evermem, parse_groupmem, score
from evog.benchmarks import compare, metrics, run
from evog.config import Settings
from evog.demo import DemoProvider
from evog.errors import ContractError, ProviderError
from evog.providers import ModelReply


def test_evermem_adapter_preserves_gold_outside_messages(tmp_path):
    root = tmp_path / "evermem"
    (root / "dataset" / "01").mkdir(parents=True)
    (root / "dataset" / "01" / "dialogue.json").write_text(
        json.dumps(
            {
                "dialogues": {
                    "2025-01-01": {
                        "Group 1": [
                            {
                                "dialogue": "hello",
                                "message_index": 1,
                                "speaker": "A",
                                "time": "2025-01-01 10:00:00",
                            }
                        ]
                    }
                }
            }
        ),
        encoding="utf-8",
    )
    (root / "dataset" / "01" / "qa_01.json").write_text(
        json.dumps(
            {
                "qars": [
                    {
                        "id": "F_SH_1",
                        "Q": "What?",
                        "A": "secret-gold",
                        "R": [{"private-evidence": "gold-locator"}],
                        "options": None,
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    episodes = load_episodes("evermembench", root, topics=["01"], limit=1)
    corpus = load_corpus("evermembench", root, "01")
    messages = corpus.messages
    assert len(messages) == 1 and len(episodes) == 1
    assert episodes[0].gold == "secret-gold"
    assert "secret-gold" not in corpus.messages[0].model_dump_json()
    assert "gold-locator" not in episodes[0].prompt()
    assert "secret-gold" not in episodes[0].prompt()
    assert messages[0].message_id == "2025-01-01:1"
    assert messages[0].metadata["message_index"] == "1"
    assert corpus.group_ids == [messages[0].group_id]


def test_groupmem_adapter_maps_questions_and_reply_metadata(tmp_path):
    root = tmp_path / "groupmem"
    (root / "data" / "final" / "Finance").mkdir(parents=True)
    (root / "questions" / "Finance").mkdir(parents=True)
    (
        root / "data" / "final" / "Finance" / "synthetic_domain_channels_rolevariants_Finance.json"
    ).write_text(
        json.dumps(
            {
                "Channel": [
                    {
                        "msg_node": "Msg_1",
                        "content": "decision",
                        "author": "User_1",
                        "timestamp": "2025-01-01T00:00:00",
                        "reply_to": None,
                        "role": "Owner",
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    (root / "questions" / "Finance" / "multi_hop.jsonl").write_text(
        json.dumps(
            {
                "id": "multi_hop_1",
                "question": "What?",
                "answer": "decision",
                "asking_user_id": "User_1",
            }
        )
        + "\n",
        encoding="utf-8",
    )
    episodes = load_episodes(
        "groupmembench", root, domains=["Finance"], question_types=["multi_hop"], limit=1
    )
    messages = load_corpus("groupmembench", root, "Finance").messages
    assert messages[0].metadata["role"] == "Owner"
    assert episodes[0].asking_user_id == "User_1"
    assert "User_1" in episodes[0].prompt()
    assert "decision" not in episodes[0].prompt()
    assert load_corpus("groupmembench", root, "Finance").group_ids == [messages[0].group_id]


@pytest.fixture
def ever_root(tmp_path):
    root = tmp_path / "evermem"
    folder = root / "dataset" / "01"
    folder.mkdir(parents=True)
    (folder / "dialogue.json").write_text(
        json.dumps(
            {
                "dialogues": {
                    "2025-01-05": {
                        "Group 1": [
                            {
                                "dialogue": "The release is scheduled for January 12.",
                                "message_index": 1,
                                "speaker": "Maya",
                                "time": "2025-01-05 09:00:00",
                            },
                            {
                                "dialogue": "The release schedule has changed to January 15.",
                                "message_index": 2,
                                "speaker": "Noah",
                                "time": "2025-01-05 10:00:00",
                            },
                        ],
                        "Empty": None,
                    },
                    "2025-01-06": {
                        "Group 1": [
                            {
                                "dialogue": "The schedule was confirmed.",
                                "message_index": 1,
                                "speaker": "Noah",
                                "time": "2025-01-06 10:00:00",
                            }
                        ]
                    },
                }
            }
        ),
        encoding="utf-8",
    )
    (folder / "qa_01.json").write_text(
        json.dumps(
            {
                "qars": [
                    {"id": "F_SH_Top01_001", "Q": "Latest release schedule?", "A": "January 15"},
                    {
                        "id": "MA_C_Top01_001",
                        "Q": "Which schedule?",
                        "A": "B",
                        "options": ["A. January 12", "B) January 15"],
                    },
                ]
            }
        ),
        encoding="utf-8",
    )
    return root


def test_source_date_coordinates_are_unique_and_timezone_is_explicit(ever_root):
    corpus = load_corpus("evermembench", ever_root, "01", "Asia/Shanghai")
    assert len(corpus.messages) == 3
    assert len({message.ref for message in corpus.messages}) == 3
    assert len(corpus.group_ids) == 1
    assert corpus.messages[0].timestamp.isoformat().endswith("+08:00")
    assert corpus.messages[0].metadata["assumed_timezone"] == "Asia/Shanghai"


def test_episode_filter_and_multiple_choice_options(ever_root, tmp_path):
    split = tmp_path / "ids.txt"
    split.write_text("# Episode selection\nMA_C_Top01_001\n", encoding="utf-8")
    rows = load_episodes("evermembench", ever_root, episode_file=split)
    assert len(rows) == 1 and rows[0].options == {"A": "January 12", "B": "January 15"}
    assert "Options:" in rows[0].prompt()
    assert "gold" not in rows[0].prompt()
    split.write_text("missing-id\n", encoding="utf-8")
    with pytest.raises(ContractError, match="outside"):
        load_episodes("evermembench", ever_root, episode_file=split)
    with pytest.raises(ContractError, match="positive"):
        load_episodes("evermembench", ever_root, limit=0)


def test_multiple_choice_uses_direct_scoring_without_a_model():
    episode = Episode(
        benchmark="evermembench",
        episode_id="MA_C_1",
        question="Which?",
        gold="B",
        options={"A": "one", "B": "two"},
        scope="01",
        question_type="MA_C",
    )
    provider = ScriptedProvider()
    assert score(provider, episode, "Choose **B**.")["passed"] is True
    assert score(provider, episode, "A")["passed"] is False
    assert not provider.calls


@pytest.mark.parametrize(
    "content,passed",
    [
        ('Explanation\n```json\n{"label":"CORRECT"}\n```', True),
        ('{"label":"WRONG"}', False),
        ("unreadable", None),
    ],
)
def test_evermem_official_verdict_parser(content, passed):
    assert parse_evermem(content) is passed


@pytest.mark.parametrize(
    "content,passed",
    [
        ("Reasoning.\nFinal: Correct", True),
        ("Final: Incorrect", False),
        ("Final: Correct\nFinal answer: Not correct", False),
        ("unknown", None),
    ],
)
def test_groupmem_official_verdict_parser(content, passed):
    assert parse_groupmem(content) is passed


def test_judge_failures_remain_unscored():
    episode = Episode(
        benchmark="groupmembench",
        episode_id="id",
        question="What?",
        gold="secret-gold",
        scope="Finance",
        question_type="multi_hop",
    )
    provider = ScriptedProvider(ProviderError("unavailable"))
    assert score(provider, episode, "candidate")["passed"] is None
    provider = ScriptedProvider(*[ModelReply(content="unknown") for _ in range(3)])
    judged = score(provider, episode, "candidate")
    assert judged["status"] == "judge_unparseable" and judged["attempts"] == 3
    assert "secret-gold" in provider.calls[0][0][1]["content"]


def test_paired_regressions_and_missing_measurements():
    before = [
        {"episode_id": str(i), "passed": passed}
        for i, passed in enumerate([False, True, True, False, None])
    ]
    after = [
        {"episode_id": str(i), "passed": passed}
        for i, passed in enumerate([True, False, True, False, True])
    ]
    paired = compare(before, after)
    assert all(
        paired[key] == 1
        for key in ["fail_to_pass", "pass_to_fail", "pass_to_pass", "fail_to_fail", "unscored"]
    )
    with pytest.raises(ContractError, match="identical"):
        compare(before, after[:-1])
    summary = metrics(before)
    assert summary["unscored"] == 1 and summary["pass_rate"] == 0.4


def test_complete_benchmark_cycle_and_persisted_validation(ever_root, tmp_path):
    class CycleProvider(DemoProvider):
        def complete(self, messages, tools):
            if messages[0]["content"].startswith("You are an expert grader"):
                return ModelReply(content='{"label":"CORRECT"}')
            return super().complete(messages, tools)

    output = tmp_path / "results.json"
    settings = Settings(max_turns=4, analysis_turns=3)
    with Application(tmp_path / "workspace", settings=settings, provider=CycleProvider()) as app:
        result = run(
            app, "evermembench", ever_root, output=output, topics=["01"], limit=1, cycle=True
        )
        assert result["status"] == "completed"
        assert result["activated"]["validation"] == "business"
        assert result["comparison"]["pass_to_fail"] == 0
        assert result["candidate"]["metrics"]["passed"] == 1
        assert app.store.revisions()[-1]["validation"] == "business"
        assert len(list((app.store.workspace / "sessions").glob("*/memory"))) == 2
        assert (
            "January 15"
            not in app.store.run(result["baseline"]["results"][0]["run_id"])["question"]
        )
        with pytest.raises(ContractError, match="already exists"):
            run(app, "evermembench", ever_root, output=output, limit=1)
    assert json.loads(output.read_text())["evolution_status"] == "activated"
