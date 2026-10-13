import pytest

from video_ingest.ocr import consolidate, is_noise, norm, within_one_edit


def frames(*texts):
    """Each argument is one image: a '|'-separated string of OCR lines."""
    return [[t.strip() for t in img.split("|") if t.strip()] for img in texts]


def test_norm_folds_accents_and_punctuation():
    assert norm("Oncé oil is hot; fry!") == "onceoilishotfry"


@pytest.mark.parametrize(
    "text",
    ["TikTok", "JTikTok", "TikToK", "TikTOk", "@cookingwithadriano", "ok", "a.", "  "],
)
def test_is_noise(text):
    assert is_noise(text, set())


@pytest.mark.parametrize("text", ["Salt", "Add milk", "70g Protein", "TikTok famous pasta"])
def test_is_not_noise(text):
    assert not is_noise(text, set())


def test_consolidate_dedupes_across_frames_in_first_seen_order():
    images = frames(
        "TikTok | @chef | Chicken breast | Flour",
        "Chicken breast | Flour | TikTok",
        "Slice chicken breasts in half | @chef",
        "Chicken breast",  # reappears later: still listed once, in its first position
    )
    assert consolidate(images) == ["Chicken breast", "Flour", "Slice chicken breasts in half"]


def test_consolidate_picks_most_common_spelling():
    images = frames(
        "Oncé oil is hot; fry breaded",
        "Once oil is hot, fry breaded",
        "Once oil is hot, fry breaded",
        "Once oil is hot, fry breaded",
    )
    assert consolidate(images) == ["Once oil is hot, fry breaded"]


def test_consolidate_keeps_distinct_but_similar_lines():
    assert consolidate(frames("1 Tbsp Ranch Seasoning", "2 Tbsp Ranch Seasoning")) == [
        "1 Tbsp Ranch Seasoning",
        "2 Tbsp Ranch Seasoning",
    ]


def test_consolidate_drops_handle_seen_without_at_sign():
    images = frames("@nikitafair | 70g Protein", "nikitafair | 450 Calories")
    assert consolidate(images) == ["70g Protein", "450 Calories"]


def test_consolidate_uses_given_handles():
    assert consolidate(frames("fairfiteats | Salt"), handles={"FairFitEats"}) == ["Salt"]


def test_consolidate_drops_burned_in_subtitles_but_keeps_short_lines():
    transcript = "Next, we're going to take out 20 ounces of chicken breast, add salt."
    images = frames("we're going to take out 20 ounces | Salt | 20oz Chicken Breast")
    assert consolidate(images, transcript=transcript) == ["Salt", "20oz Chicken Breast"]


def test_consolidate_merges_jitter_that_keeps_digits():
    images = frames("cutlets for 5-7.minutes on", "cutlets for 5-7 minutes on")
    assert len(consolidate(images)) == 1


def test_consolidate_collapses_whitespace():
    assert consolidate(frames("Fresh   parsley ")) == ["Fresh parsley"]


def test_consolidate_empty():
    assert consolidate([]) == []
    assert consolidate(frames("TikTok | @x")) == []


@pytest.mark.parametrize(
    ("a", "b", "expected"),
    [
        ("flour", "fiour", True),
        ("flour", "flours", True),
        ("flour", "lour", True),
        ("flour", "flower", False),
        ("salt", "salt", True),
        ("abc", "abcde", False),
    ],
)
def test_within_one_edit(a, b, expected):
    assert within_one_edit(a, b) is expected
    assert within_one_edit(b, a) is expected


def test_consolidate_merges_one_letter_misreads_of_short_words():
    assert consolidate(frames("Flour", "Flour", "Fiour")) == ["Flour"]
    assert consolidate(frames("Salt", "Sugar")) == ["Salt", "Sugar"]


def test_consolidate_strips_on_screen_bullets():
    assert consolidate(frames("- 60ml soy sauce", "• 3 eggs", "-- 10ml mirin")) == [
        "60ml soy sauce",
        "3 eggs",
        "10ml mirin",
    ]


def test_consolidate_drops_half_typed_prefixes():
    images = frames("4 SERVI", "4 SERVINGS", "Per burrito (makes", "Pér burrito (makes 6)")
    assert consolidate(images) == ["4 SERVINGS", "Pér burrito (makes 6)"]


def test_consolidate_keeps_short_prefixes():
    assert consolidate(frames("Egg", "Eggs and milk")) == ["Egg", "Eggs and milk"]
