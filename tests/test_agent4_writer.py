from pipeline.agent4_writer import (
    build_chapter_prompt, build_title_prompt, build_inspiration_prompt,
    remove_ai_cliches, detect_dialogue_imbalance, post_process_chapter,
)


def test_build_chapter_prompt():
    context = "【相关角色】\n- 林羽: 剑修\n"
    outline = "林羽进入秘境，遭遇妖兽"
    style = {"dialogue_ratio": 0.3, "camera_sequence": "先环境后人物"}
    ref_style = "对标书《剑来》片段：剑气纵横三万里..."
    msgs = build_chapter_prompt(outline, context, style, ref_style)
    assert len(msgs) == 2
    assert msgs[0]["role"] == "system"
    assert "林羽" in msgs[1]["content"]
    assert "剑来" in msgs[1]["content"]
    assert "Show, Don't Tell" in msgs[0]["content"]


def test_build_title_prompt():
    msgs = build_title_prompt("废柴逆袭", "玄幻", count=3)
    assert "3 个" in msgs[1]["content"]
    assert "玄幻" in msgs[1]["content"]


def test_build_inspiration_prompt():
    refs = ["参考《斗破苍穹》中类似的退婚打脸桥段"]
    msgs = build_inspiration_prompt("卡文了，主角被围杀怎么破局", refs)
    assert "退婚打脸" in msgs[1]["content"]


def test_remove_ai_cliches():
    text = "总而言之，林羽非常愤怒。他嘴角勾起一抹玩味的笑。"
    cleaned = remove_ai_cliches(text)
    assert "总而言之" not in cleaned
    assert "嘴角勾起一抹玩味的笑" not in cleaned


def test_remove_ai_cliches_preserves_normal_text():
    text = "林羽走在山路上，远处有炊烟升起。"
    cleaned = remove_ai_cliches(text)
    assert cleaned == text


def test_detect_dialogue_imbalance():
    text_with_long_dialogue = "林羽说：" + "我很强。" * 60
    issues = detect_dialogue_imbalance(text_with_long_dialogue)
    assert len(issues) > 0


def test_detect_dialogue_imbalance_normal():
    text = "林羽握紧拳头。" * 20 + '"来吧。"他说。\n' + "对手冲了过来。" * 10
    issues = detect_dialogue_imbalance(text)
    assert len(issues) == 0


def test_post_process_chapter():
    raw = '总而言之，林羽心中涌起一股不可名状的感觉。\n\n他走在小路上，看到一只鸟飞过。'
    processed = post_process_chapter(raw)
    assert "总而言之" not in processed
    assert "不可名状" not in processed
