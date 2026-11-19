"""Question correction and uploaded raster validation boundaries."""

from base64 import b64encode
from io import BytesIO

import pytest
from PIL import Image
from pydantic import ValidationError

from app.schemas.quiz import ChoiceRule, NumberRule, QuestionFields, TextRule
from app.services.errors import AuthError
from app.services.quiz import answer_matches, prepare_image


@pytest.mark.parametrize(
    ("value", "correct"),
    [
        ("1/2", True),
        ("0.5", True),
        ("0,5", True),
        ("0.49", True),
        ("0.51", True),
        ("0,489", False),
        ("0,51001", False),
    ],
)
def test_numeric_answers(value: str, correct: bool) -> None:
    """Accept rational equivalents and enforce inclusive exact tolerance boundaries."""
    rule = NumberRule(kind="number", expected="1/2", tolerance="0,01")
    assert answer_matches(rule, value) is correct


@pytest.mark.parametrize("value", ["1/0", "0.5+0", "NaN", "1e1000", "0.5 m"])
def test_invalid_number(value: str) -> None:
    """Reject invalid fractions, expressions, units and unbounded exponents."""
    rule = NumberRule(kind="number", expected="0,5")
    with pytest.raises(AuthError) as caught:
        answer_matches(rule, value)
    assert caught.value.status == 422


def test_normalized_text_and_exact_choice_set() -> None:
    """Ignore text casing and accents and require precisely the correct options."""
    text = TextRule(kind="text", accepted=["Ampère", "ampères"])
    assert answer_matches(text, "  AMPÉRE ")
    assert answer_matches(text, "ampere")
    assert not answer_matches(text, "un ampère")
    choices = ChoiceRule(kind="choice", options=["A", "B", "C"], correct=[0, 2])
    assert answer_matches(choices, [2, 0])
    assert not answer_matches(choices, [0])
    assert not answer_matches(choices, [0, 1, 2])
    with pytest.raises(AuthError):
        answer_matches(choices, [0, 0])


def test_image_validation() -> None:
    """Accept a real image beyond the default string limit and reject content spoofing."""
    with BytesIO() as output:
        Image.effect_noise((128, 128), 100).save(output, format="PNG")
        encoded = b64encode(output.getvalue()).decode("ascii")
    assert len(encoded) > 4000
    data = QuestionFields(
        title="Figure",
        prompt="Identifiez la notation.",
        rule=TextRule(kind="text", accepted=["A"]),
        image="data:image/png;base64," + encoded,
        image_alt="Notation",
    )
    assert prepare_image(data.image).startswith("data:image/png;base64,")
    with pytest.raises(AuthError):
        prepare_image("data:image/jpeg;base64," + encoded)
    with pytest.raises(ValidationError):
        QuestionFields.model_validate({**data.model_dump(), "image_alt": ""})


def test_image_rejects_excessive_dimensions_with_a_specific_message() -> None:
    """Explain why a small but high-resolution raster cannot be uploaded."""
    with BytesIO() as output:
        Image.new("RGB", (2001, 2000)).save(output, format="PNG")
        encoded = b64encode(output.getvalue()).decode("ascii")
    assert len(encoded) < 1024 * 1024
    with pytest.raises(AuthError, match="4 mégapixels"):
        prepare_image("data:image/png;base64," + encoded)


def test_prepare_jpeg_without_frame_count() -> None:
    """Save a regular single-frame JPEG even when Pillow omits its frame count."""
    with BytesIO() as original:
        Image.new("RGB", (128, 128), "blue").save(original, format="JPEG")
        encoded = b64encode(original.getvalue()).decode("ascii")
    assert prepare_image("data:image/jpeg;base64," + encoded).startswith("data:image/jpeg;base64,")
