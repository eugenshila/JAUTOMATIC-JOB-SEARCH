"""Unit tests for application building: question mapping, attachments, safety."""

import pytest
from conftest import make_config

from jauto.applier import Applier
from jauto.db import Store
from jauto.models import Job
from jauto.providers import (
    ApplicationSpec,
    GreenhouseProvider,
    Question,
    T_FILE,
    T_MULTI,
    T_SINGLE,
    T_TEXT,
    T_TEXTAREA,
    build_providers,
)


@pytest.fixture
def applier(tmp_path):
    config = make_config(tmp_path)
    store = Store(str(tmp_path / "jauto.db"))
    providers = build_providers(FakeClientStub(), lever_apply_key="")
    return Applier(config, store, providers), config, store


class FakeClientStub:
    """Client stub — no network calls expected in these unit tests."""


def _spec_fixture_1():
    return ApplicationSpec(
        questions=[
            Question("first_name", "First Name", T_TEXT, required=True, kind="standard"),
            Question("last_name", "Last Name", T_TEXT, required=True, kind="standard"),
            Question("email", "Email", T_TEXT, required=True, kind="standard"),
            Question("phone", "Phone", T_TEXT, required=True, kind="standard"),
            Question("resume", "Resume/CV", T_FILE, required=True, kind="standard"),
            Question("resume_text", "Resume/CV", T_TEXTAREA, required=False, kind="standard"),
            Question("cover_letter", "Cover Letter", T_FILE, required=False, kind="standard"),
            Question("cover_letter_text", "Cover Letter", T_TEXTAREA, required=False, kind="standard"),
            Question("question_5555", "LinkedIn Profile", T_TEXT, required=True),
            Question(
                "question_3333",
                "Are you legally authorized to work in the US?",
                T_SINGLE,
                required=True,
                options=[(1, "Yes"), (0, "No")],
            ),
            Question("question_7777", "How did you hear about us?", T_TEXT, required=False),
        ]
    )


def _job():
    return Job(
        provider="greenhouse",
        provider_board="acme",
        provider_job_id="900001",
        company="Acme Corp",
        title="Software Engineer, Backend",
        location="Remote - US",
        remote=True,
    )


def test_build_maps_standard_fields(applier):
    app_builder, config, _ = applier
    built = app_builder.build(_job(), _spec_fixture_1(), endpoint="greenhouse")
    assert built.form["first_name"] == "Jane"
    assert built.form["last_name"] == "Doe"
    assert built.form["email"] == "jane.doe@example.com"
    assert built.form["phone"] == "+254700000000"


def test_build_attaches_resume_file(applier):
    app_builder, config, _ = applier
    built = app_builder.build(_job(), _spec_fixture_1(), endpoint="greenhouse")
    resume_fields = [f for f, _n, _c in built.files if f == "resume"]
    assert resume_fields == ["resume"]
    content = next(c for f, n, c in built.files if f == "resume")
    assert content.startswith(b"%PDF-")
    assert built.ready


def test_build_cover_letter_from_template(applier):
    app_builder, config, _ = applier
    built = app_builder.build(_job(), _spec_fixture_1(), endpoint="greenhouse")
    cover = built.form.get("cover_letter_text", "")
    assert "Acme Corp" in cover
    assert "Software Engineer, Backend" in cover
    assert "Jane Doe" in cover


def test_build_maps_configured_answers_to_options(applier):
    app_builder, config, _ = applier
    built = app_builder.build(_job(), _spec_fixture_1(), endpoint="greenhouse")
    # config answers 'legally authorized' -> 'Yes' -> option value 1
    assert built.form["question_3333"] == 1


def test_build_links_questions(applier):
    app_builder, config, _ = applier
    built = app_builder.build(_job(), _spec_fixture_1(), endpoint="greenhouse")
    assert built.form["question_5555"] == "https://www.linkedin.com/in/janedoe"


def test_unmapped_required_question_blocks_submission(applier):
    app_builder, config, _ = applier
    spec = ApplicationSpec(
        questions=[
            Question("first_name", "First Name", T_TEXT, required=True, kind="standard"),
            Question("email", "Email", T_TEXT, required=True, kind="standard"),
            Question("resume", "Resume/CV", T_FILE, required=True, kind="standard"),
            Question("question_9999", "What is your favorite color?", T_TEXT, required=True),
        ]
    )
    built = app_builder.build(_job(), spec, endpoint="greenhouse")
    assert not built.ready
    assert any("favorite color" in m for m in built.missing_required)
    # optional unmapped questions are only noted
    assert built.unmapped_optional == []


def test_select_answer_with_no_matching_option_is_missing(applier):
    app_builder, config, _ = applier
    config.apply.answers["legally authorized"] = "Maybe"
    spec = ApplicationSpec(
        questions=[
            Question(
                "question_1",
                "Are you legally authorized to work in the US?",
                T_SINGLE,
                required=True,
                options=[(1, "Yes"), (0, "No")],
            )
        ]
    )
    built = app_builder.build(_job(), spec, endpoint="greenhouse")
    assert not built.ready
    assert any("does not match any option" in m for m in built.missing_required)


def test_multi_select_comma_separated_answers(applier):
    app_builder, config, _ = applier
    config.apply.answers["programming languages"] = "Python, Go"
    spec = ApplicationSpec(
        questions=[
            Question(
                "question_2",
                "Which programming languages do you know?",
                T_MULTI,
                required=True,
                options=[(10, "Python"), (11, "Go"), (12, "Rust")],
            )
        ]
    )
    built = app_builder.build(_job(), spec, endpoint="greenhouse")
    assert built.form["question_2"] == [10, 11]
    assert built.ready


def test_eeo_answers_mapped_by_label(applier):
    app_builder, config, _ = applier
    config.apply.eeo_answers["gender"] = "Prefer not to say"
    spec = ApplicationSpec(
        questions=[
            Question(
                "gender",
                "Please select your gender",
                T_SINGLE,
                required=True,
                options=[(1, "Male"), (2, "Female"), (3, "Prefer not to say")],
                kind="eeo",
            )
        ]
    )
    built = app_builder.build(_job(), spec, endpoint="greenhouse")
    assert built.form["gender"] == 3
    assert built.ready


def test_gdpr_consent_required_but_not_configured(applier):
    app_builder, config, _ = applier
    spec = ApplicationSpec(questions=[], requires_gdpr_consent=True)
    built = app_builder.build(_job(), spec, endpoint="greenhouse")
    assert not built.ready
    assert any("GDPR" in m for m in built.missing_required)


def test_gdpr_consent_configured(applier):
    app_builder, config, _ = applier
    config.apply.consent_gdpr = True
    spec = ApplicationSpec(questions=[], requires_gdpr_consent=True)
    built = app_builder.build(_job(), spec, endpoint="greenhouse")
    assert built.form["data_compliance[gdpr_consent_given]"] == "1"
    assert built.form["data_compliance[gdpr_processing_consent_given]"] == "1"
    assert built.ready


def test_missing_resume_blocks_when_required(applier):
    app_builder, config, _ = applier
    config.profile.resume_path = "nonexistent.pdf"
    spec = ApplicationSpec(
        questions=[
            Question("resume", "Resume/CV", T_FILE, required=True, kind="standard"),
        ]
    )
    built = app_builder.build(_job(), spec, endpoint="greenhouse")
    assert not built.ready


def test_preferred_name_falls_back_to_first_name(applier):
    app_builder, config, _ = applier
    spec = ApplicationSpec(
        questions=[Question("preferred_name", "Preferred First Name", T_TEXT, required=True)]
    )
    built = app_builder.build(_job(), spec, endpoint="greenhouse")
    assert built.form["preferred_name"] == "Jane"
