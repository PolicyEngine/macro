from policyengine_macro import capabilities


def test_registry_has_exact_integrated_models():
    assert set(capabilities.MODELS) == {
        "pe-microsim", "obr-macro", "boe-svar", "frb-us", "us-hank", "og-uk",
        "og+microsim", "define-uk",
    }


def test_og_is_uk_only_and_experimental():
    og = capabilities.get_status("og-uk")
    assert og["geography"] == ["uk"]
    assert "research prototype" in og["status"]


def test_router_refuses_unsupported_mapping():
    result = capabilities.recommend("forecast", country="us")
    assert result["primary_model"] is None
    assert result["warning"]


def test_router_selects_distribution_model():
    result = capabilities.recommend(
        "policy_reform", country="uk", needs_distribution=True
    )
    assert result["primary_model"] == "pe-microsim"


def test_every_model_declares_adapter_acceptance_metadata():
    capabilities.validate_registry()
    for model in capabilities.list_capabilities():
        assert model["inputs"]
        assert model["outputs"]
        assert model["data_vintage"]
        assert model["cannot_answer"]


def test_quality_contract_separates_fidelity_from_economic_evidence():
    obr = capabilities.get_status("obr-macro")["quality"]
    svar = capabilities.get_status("boe-svar")["quality"]
    frbus = capabilities.get_status("frb-us")["quality"]

    assert set(obr) == capabilities.QUALITY_DIMENSIONS
    assert obr["predictive_validation"]["level"] == "weak"
    assert svar["identification_robustness"]["level"] == "moderate"
    assert frbus["implementation_fidelity"]["level"] == "strong"
    assert frbus["predictive_validation"]["level"] == "not_assessed"


def test_quality_assessments_are_explanatory_not_numeric_scores():
    for model in capabilities.list_capabilities():
        for assessment in model["quality"].values():
            assert assessment["level"] in capabilities.QUALITY_LEVELS
            assert assessment["evidence"]
            assert assessment["next_gate"]
            assert "score" not in assessment


def test_distribution_routing_keeps_dynamic_member():
    """Reverting the needs_distribution filter to pe-microsim-only must
    fail here, not pass silently."""
    rec = capabilities.recommend(
        "policy_reform", country="uk", needs_distribution=True
    )
    assert "og+microsim" in rec["candidate_models"]


def test_every_model_has_a_real_evidence_assessment():
    """No model may ship the auto-filled placeholder quality entry.

    MODEL_QUALITY originally covered three macro models, and every other
    member fell through to a generated block of `not_assessed` dimensions
    whose evidence string read "Outside the scope of the current three-model
    audit." That is a placeholder, not an assessment — but `get_status` and
    `list_capabilities` serve it in the same shape as a real one, so a
    consumer could not tell a considered "not_applicable" from an unexamined
    gap. Four of the eight models were in that state, including the one the
    site leads with.

    not_applicable and a reasoned not_assessed are both legitimate: a
    microsimulation has no forecast error, and frb-us honestly records that
    no forecast evaluation has been run here and names the one that would
    settle it. What is not acceptable is the generated fallback text, which
    asserts nothing while being served in the same shape as a judgement.
    """
    PLACEHOLDER = "No evidence review has been completed"
    for model_id in capabilities.MODELS:
        assert model_id in capabilities.MODEL_QUALITY, (
            f"{model_id} has no MODEL_QUALITY entry and would fall back to "
            "the placeholder"
        )
        entry = capabilities.MODEL_QUALITY[model_id]
        assert set(entry) == capabilities.QUALITY_DIMENSIONS, (
            f"{model_id} is missing dimensions: "
            f"{sorted(capabilities.QUALITY_DIMENSIONS - set(entry))}"
        )
        for dimension, judgement in entry.items():
            assert judgement["level"] in capabilities.QUALITY_LEVELS, (
                f"{model_id}.{dimension}: {judgement['level']!r} is not a "
                f"recognised level"
            )
            # not_assessed is a legitimate verdict when it is reasoned:
            # frb-us records that no forecast evaluation is published here
            # and names the run that would change it. What is forbidden is
            # the generated fallback, which asserts nothing and is
            # indistinguishable from a real judgement in the served payload.
            assert PLACEHOLDER not in judgement["evidence"], (
                f"{model_id}.{dimension} carries the placeholder evidence "
                "string — write the review, or record the level with a "
                "reason specific to this model"
            )
            if judgement["level"] == "not_assessed":
                assert judgement["next_gate"].strip(), (
                    f"{model_id}.{dimension} is not_assessed with no "
                    "next_gate, so nothing says what would settle it"
                )
            assert judgement["evidence"].strip(), (
                f"{model_id}.{dimension} has an empty evidence string"
            )


def test_public_site_names_resolve_through_the_api():
    """A name the site publishes must work in the API the site documents.

    site_id was added so pages render one name per model, but the alias was
    one-directional: every page said `psl-og` while `get_status("psl-og")`
    raised, and the error listed only registry keys — so a reader who took the
    documented name into the documented tool got a hard failure with nothing
    connecting the two. Resolution now goes both ways, and the returned
    model_id is the registry key, so a caller who passed a site name learns
    the contract id.
    """
    for site_name, expected_key in capabilities.SITE_ID_TO_KEY.items():
        assert capabilities.get_status(site_name)["model_id"] == expected_key
        assert capabilities.get_status(expected_key)["model_id"] == expected_key

    try:
        capabilities.get_status("not-a-model")
    except ValueError as error:
        message = str(error)
        assert "og-uk" in message and "psl-og" in message, message
    else:
        raise AssertionError("an unknown model_id must raise")
