from pipeline.agent1_cleaner import (
    parse_file, clean_text, split_into_chapters, chunk_chapter, Chunk,
)

SAMPLE_TXT = b"\xe7\xac\xac\xe4\xb8\x80\xe7\xab\xa0 \xe5\xba\x9f\xe6\x9f\xb4\xe5\xb0\x91\xe5\xb9\xb4\n\n\xe2\x80\x9c\xe6\x88\x91\xe6\x98\xaf\xe5\xba\x9f\xe6\x9f\xb4\xef\xbc\x9f\xe2\x80\x9d\xe6\x9e\x97\xe7\xbe\xbd\xe6\x8f\xa1\xe7\xb4\xa7\xe6\x8b\xb3\xe5\xa4\xb4\xe3\x80\x82\n\n\xe5\x8a\xa0\xe5\xbe\xae\xe4\xbf\xa1kanshu123\xe7\x9c\x8b\xe6\x9b\xb4\xe5\xa4\x9a\xef\xbc\x81\n\n\xe4\xbb\x96\xe7\xab\x99\xe8\xb5\xb7\xe8\xba\xab\xef\xbc\x8c\xe8\xb5\xb0\xe5\x90\x91\xe5\xb1\xb1\xe9\x97\xa8\xe3\x80\x82\n\n\xe7\xac\xac\xe4\xba\x8c\xe7\xab\xa0 \xe6\x84\x8f\xe5\xa4\x96\xe8\xa7\x89\xe9\x86\x92\n\n\xe4\xb8\x80\xe9\x81\x93\xe9\x87\x91\xe5\x85\x89\xe4\xbb\x8e\xe5\xa4\xa9\xe8\x80\x8c\xe9\x99\x8d\xe3\x80\x82"

SAMPLE_CN = "第一章 废柴少年\n\n" + "“我是废柴？”林羽握紧拳头。\n\n加微信kanshu123看更多！\n\n他站起身，走向山门。\n\n第二章 意外觉醒\n\n一道金光从天而降。"


def test_parse_txt():
    import tempfile, os
    with tempfile.NamedTemporaryFile(suffix=".txt", delete=False, mode="wb") as f:
        f.write(SAMPLE_CN.encode("utf-8"))
        path = f.name
    try:
        text = parse_file(path)
        assert "林羽握紧拳头" in text
    finally:
        os.unlink(path)


def test_clean_text_removes_ads():
    raw = "第一章 废柴少年\n加微信kanshu123看更多！\n林羽握紧拳头。\n\n作者说：求收藏求推荐！\n他站起身。"
    cleaned = clean_text(raw)
    assert "加微信" not in cleaned
    assert "作者说" not in cleaned
    assert "林羽握紧拳头" in cleaned


def test_clean_text_collapses_excessive_punctuation():
    raw = "什么！！！！不可能……"
    cleaned = clean_text(raw)
    assert cleaned == "什么！不可能……"


def test_clean_text_fixes_broken_lines():
    raw = "林羽站在山门前，\n望向前方。\n他深吸一口气，\n踏出了第一步。"
    cleaned = clean_text(raw)
    assert cleaned.count("\n") <= 1


def test_split_into_chapters():
    text = "第一章 废柴\n林羽的故事。\n\n第二章 觉醒\n金光闪烁。"
    chapters = split_into_chapters(text)
    assert len(chapters) == 2
    assert chapters[0]["title"] == "第一章 废柴"
    assert "林羽的故事" in chapters[0]["content"]


def test_split_into_chapters_no_explicit_chapter():
    text = "林羽走在路上。\n\n他看到了远方。"
    chapters = split_into_chapters(text)
    assert len(chapters) == 1
    assert chapters[0]["title"] == "正文"


def test_chunk_chapter():
    text = "林羽握拳。" * 3000
    chunks = chunk_chapter(text, chapter_index=0, tokens_per_chunk=500, overlap_tokens=50)
    assert len(chunks) > 1
    assert all(isinstance(c, Chunk) for c in chunks)


def test_chunk_structure():
    text = "林羽握拳。" * 100
    chunks = chunk_chapter(text, chapter_index=0, tokens_per_chunk=500, overlap_tokens=100)
    for c in chunks:
        assert c.chunk_id
        assert c.chapter_index == 0
        assert c.content
        assert c.token_count > 0
