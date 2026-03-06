from pathlib import Path

class PromptPaths:
    def __init__(self, base="prompt"):
        self.base = Path(base)
        self.prompts = {
            name: self.base / f"{name}.txt"
            for name in [
                "identify_incident",
                "identify_hazard_consequence",
                "identify_condition",
                "identify_evidence",
                "extract_event",
                "identify_relationship",
                "chain_events",
                "chain_conditions_events",
                "chain_scenario",
                "chain_hazards",
                "prep_final_check",
            ]
        }

    def __getitem__(self, key):
        return self.prompts[key]

    def __getattr__(self, key):
        return self.prompts[key]
    
    def load_all(self):
        return {name: path.read_text(encoding="utf-8") for name, path in self.prompts.items()}

prompts = PromptPaths()
