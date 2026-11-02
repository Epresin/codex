use super::*;
use codex_models_manager::model_info::model_info_from_slug;
use pretty_assertions::assert_eq;

fn model_preset(slug: &str) -> ModelPreset {
    let mut model = ModelPreset::from(model_info_from_slug(slug));
    model.show_in_picker = true;
    model
}

fn available_models() -> Vec<ModelPreset> {
    let mut models = (0..7)
        .map(|index| model_preset(&format!("model-{index}")))
        .collect::<Vec<_>>();
    let mut hidden = model_preset("hidden-model");
    hidden.show_in_picker = false;
    models.insert(0, hidden);
    let mut disabled = model_preset("disabled-model");
    disabled.multi_agent_version = Some(MultiAgentVersion::Disabled);
    models.insert(1, disabled);
    models
}

#[test_case::test_case(MultiAgentVersion::V1; "v1")]
#[test_case::test_case(MultiAgentVersion::V2; "v2")]
fn subagent_model_catalog_unknown_model_lists_all_visible_supported_candidates(
    version: MultiAgentVersion,
) {
    let error = find_spawn_agent_model_name(&available_models(), "unknown-model", version)
        .expect_err("unknown model must be rejected");
    let expected_candidates = if version == MultiAgentVersion::V2 {
        "model-0, model-1, model-2, model-3, model-4, model-5, model-6"
    } else {
        "disabled-model, model-0, model-1, model-2, model-3, model-4, model-5, model-6"
    };
    assert_eq!(
        error,
        format!(
            "Unknown model `unknown-model` for spawn_agent. Available models: {expected_candidates}"
        )
    );
}

#[test_case::test_case(MultiAgentVersion::V1; "v1")]
#[test_case::test_case(MultiAgentVersion::V2; "v2")]
fn subagent_model_catalog_resolves_model_beyond_fifth_visible_choice(version: MultiAgentVersion) {
    assert_eq!(
        find_spawn_agent_model_name(&available_models(), "model-5", version),
        Ok("model-5".to_string())
    );
}

#[test]
fn subagent_model_catalog_lookup_preserves_backend_and_id_validation() {
    let models = available_models();
    assert!(find_spawn_agent_model_name(&models, "disabled-model", MultiAgentVersion::V2).is_err());
    assert_eq!(
        find_spawn_agent_model_name(&models, "disabled-model", MultiAgentVersion::V1),
        Ok("disabled-model".to_string())
    );
    assert_eq!(
        find_spawn_agent_model_name(&models, "hidden-model", MultiAgentVersion::V2),
        Ok("hidden-model".to_string())
    );
    assert!(find_spawn_agent_model_name(&models, "MODEL-5", MultiAgentVersion::V2).is_err());
}
