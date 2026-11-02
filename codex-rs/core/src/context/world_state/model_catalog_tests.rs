use super::*;
use codex_models_manager::model_info::model_info_from_slug;
use codex_protocol::openai_models::ModelServiceTier;
use codex_protocol::openai_models::ReasoningEffort;
use codex_protocol::openai_models::ReasoningEffortPreset;
use codex_protocol_test_support::ContentItemTestExt;
use pretty_assertions::assert_eq;

fn model_preset(slug: &str) -> ModelPreset {
    let mut model = ModelPreset::from(model_info_from_slug(slug));
    model.show_in_picker = true;
    model.description = "Short description".to_string();
    model.supported_reasoning_efforts = Vec::new();
    model.service_tiers = Vec::new();
    model
}

#[test_case::test_case(MultiAgentVersion::V1; "v1")]
#[test_case::test_case(MultiAgentVersion::V2; "v2")]
fn model_catalog_lists_all_visible_supported_models(version: MultiAgentVersion) {
    let mut models = (0..7)
        .rev()
        .map(|index| model_preset(&format!("model-{index}")))
        .collect::<Vec<_>>();
    let mut hidden = model_preset("hidden-model");
    hidden.show_in_picker = false;
    models.insert(0, hidden);
    let mut disabled = model_preset("disabled-model");
    disabled.multi_agent_version = Some(MultiAgentVersion::Disabled);
    models.insert(1, disabled);

    let text = ModelCatalogState::new(&models, version)
        .render()
        .expect_text();
    let mut expected = "<model_catalog>\n".to_string();
    if version != MultiAgentVersion::V2 {
        expected.push_str("- `disabled-model`: Short description\n");
    }
    for index in 0..7 {
        expected.push_str(&format!("- `model-{index}`: Short description\n"));
    }
    expected.push_str("</model_catalog>");
    assert_eq!(text, expected);
}

#[test]
fn model_catalog_keeps_all_ids_and_capabilities_beyond_old_byte_budget() {
    let mut models = (0..7)
        .rev()
        .map(|index| {
            let mut model = model_preset(&format!("model-{index}-{}<&", "identifier".repeat(40)));
            model.description = "中文<&>\"'".repeat(60);
            model.default_reasoning_effort = ReasoningEffort::Medium;
            model.supported_reasoning_efforts = vec![ReasoningEffortPreset {
                effort: ReasoningEffort::Medium,
                description: "Balanced".to_string(),
            }];
            model.service_tiers = vec![ModelServiceTier {
                id: "fast<&".to_string(),
                name: "Fast".to_string(),
                description: "Fast tier".to_string(),
            }];
            model
        })
        .collect::<Vec<_>>();
    let text = ModelCatalogState::new(&models, MultiAgentVersion::V2)
        .render()
        .expect_text();
    assert!(text.len() > 1_000);
    let escaped_description = format!(
        "{}中文&lt;&amp;&gt;…",
        "中文&lt;&amp;&gt;&quot;&apos;".repeat(35)
    );
    let mut expected = "<model_catalog>\n".to_string();
    for index in 0..7 {
        expected.push_str(&format!(
            "- `model-{index}-{}&lt;&amp;`: {escaped_description} Reasoning efforts: medium (default). Service tiers: fast&lt;&amp;.\n",
            "identifier".repeat(40)
        ));
    }
    expected.push_str("</model_catalog>");
    assert_eq!(text, expected);

    models.reverse();
    assert_eq!(
        ModelCatalogState::new(&models, MultiAgentVersion::V2)
            .render()
            .expect_text(),
        text
    );
}

#[test]
fn model_catalog_refresh_tracks_choices_beyond_fifth() {
    let mut models = (0..7)
        .map(|index| model_preset(&format!("model-{index}")))
        .collect::<Vec<_>>();
    let original = ModelCatalogState::new(&models, MultiAgentVersion::V2);
    let (snapshot, _) = original.render_diff(PreviousSectionState::Absent);
    let snapshot = snapshot.expect("catalog snapshot");
    assert!(
        original
            .render_diff(PreviousSectionState::Known(&snapshot))
            .1
            .is_empty()
    );

    models[6].description = "Updated seventh choice".to_string();
    let updated = ModelCatalogState::new(&models, MultiAgentVersion::V2);
    let (new_snapshot, updates) = updated.render_diff(PreviousSectionState::Known(&snapshot));
    assert_ne!(new_snapshot, Some(snapshot));
    assert_eq!(updates.len(), 1);
}
