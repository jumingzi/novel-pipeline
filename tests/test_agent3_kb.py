import tempfile
from pipeline.agent3_kb import (
    detect_genre, merge_character_cards, KnowledgeBase, merge_lists,
)


def test_detect_genre_xianxia():
    chars = [{"name": "林羽", "explicit_traits": "筑基期修士，剑修"}]
    assert detect_genre(chars, []) == "仙侠"


def test_detect_genre_xuanhuan():
    chars = [{"name": "萧炎", "explicit_traits": "斗者，炼药师"}]
    assert detect_genre(chars, []) == "玄幻"


def test_detect_genre_urban():
    chars = [{"name": "陈凡", "explicit_traits": "重生归来的商业巨子"}]
    result = detect_genre(chars, [])
    assert result in ["都市", "玄幻"]


def test_merge_character_cards_new_character():
    existing = []
    new_char = {"name": "林羽", "explicit_traits": "练气期", "hidden_motivation": "复仇"}
    merged = merge_character_cards(existing, [new_char])
    assert len(merged) == 1
    assert merged[0]["name"] == "林羽"


def test_merge_character_cards_upgrade():
    existing = [{"name": "林羽", "explicit_traits": "练气期", "hidden_motivation": "复仇"}]
    new_char = {"name": "林羽", "explicit_traits": "筑基期", "hidden_motivation": "复仇"}
    merged = merge_character_cards(existing, [new_char])
    assert len(merged) == 1
    assert "筑基期" in merged[0]["explicit_traits"]


def test_merge_character_cards_dedup_same():
    existing = [{"name": "林羽", "explicit_traits": "筑基期"}]
    new_char = {"name": "林羽", "explicit_traits": "筑基期"}
    merged = merge_character_cards(existing, [new_char])
    assert len(merged) == 1


class TestKnowledgeBase:
    def setup_method(self):
        self.tmpdir = tempfile.mkdtemp()

    def teardown_method(self):
        import shutil
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_save_and_load(self):
        kb = KnowledgeBase(base_dir=self.tmpdir)
        kb.save_genre_data("玄幻", {
            "characters": [{"name": "A"}],
            "plot_timeline": [],
            "world_settings": {},
            "style_profile": {},
        })
        loaded = kb.load_genre_data("玄幻")
        assert loaded["characters"][0]["name"] == "A"

    def test_update_accumulates(self):
        kb = KnowledgeBase(base_dir=self.tmpdir)
        kb.save_genre_data("玄幻", {"characters": [{"name": "A"}]})
        kb.update_genre_data("玄幻", {"characters": [{"name": "B"}]})
        loaded = kb.load_genre_data("玄幻")
        names = [c["name"] for c in loaded["characters"]]
        assert "A" in names
        assert "B" in names
