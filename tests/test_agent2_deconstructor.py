import json
from pipeline.agent2_deconstructor import (
    DeconstructionResult, build_deconstruct_prompt, parse_deconstruct_response,
)


def test_build_deconstruct_prompt_contains_chunk():
    prompt_msgs = build_deconstruct_prompt("林羽握紧拳头。")
    assert len(prompt_msgs) == 2
    assert prompt_msgs[0]["role"] == "system"
    assert "林羽握紧拳头" in prompt_msgs[1]["content"]
    assert "人设" in prompt_msgs[0]["content"]
    assert "人物关系" in prompt_msgs[0]["content"]


def test_build_deconstruct_prompt_with_sample_context():
    prompt_msgs = build_deconstruct_prompt("金光闪烁。", context_note="前情: 林羽已入宗门")
    assert "前情" in prompt_msgs[1]["content"]


def test_parse_deconstruct_response_valid_json():
    raw_json = json.dumps({
        "characters": [{"name": "林羽", "explicit_traits": "少年", "hidden_motivation": "复仇"}],
        "relationships": [],
        "dopamine_curve": {"type": "扮猪吃虎", "intensity": 4},
        "hooks": [{"type": "悬念钩", "score": 7, "description": "金光来源不明"}],
        "style_dna": {"idiom_density": 0.1, "dialogue_ratio": 0.4, "avg_sentence_length": 25},
        "foreshadowing": {"planted": [], "resolved": []},
    }, ensure_ascii=False)
    result = parse_deconstruct_response(raw_json)
    assert isinstance(result, DeconstructionResult)
    assert len(result.characters) == 1
    assert result.characters[0]["name"] == "林羽"
    assert result.dopamine_curve["type"] == "扮猪吃虎"


def test_parse_deconstruct_response_minimal():
    raw_json = json.dumps({
        "characters": [],
        "relationships": [],
        "dopamine_curve": {},
        "hooks": [],
        "style_dna": {},
        "foreshadowing": {"planted": [], "resolved": []},
    }, ensure_ascii=False)
    result = parse_deconstruct_response(raw_json)
    assert isinstance(result, DeconstructionResult)
    assert result.characters == []


def test_deconstruction_result_to_dict():
    r = DeconstructionResult(
        characters=[{"name": "A"}],
        relationships=[{"pair": ["A", "B"], "type": "师徒"}],
        dopamine_curve={"type": "升级"},
        hooks=[{"type": "利益钩", "score": 5}],
        style_dna={"idiom_density": 0.2},
        foreshadowing={"planted": [{"desc": "神秘的戒指", "chapter": 1}], "resolved": []},
    )
    d = r.to_dict()
    assert d["characters"][0]["name"] == "A"
    assert d["relationships"][0]["type"] == "师徒"
