from .step_registry import STEP_REGISTRY

__all__ = ["STEP_REGISTRY", "run_batch_pipeline"]


def run_batch_pipeline(config):
    from .runner import run_batch_pipeline as _run_batch_pipeline

    return _run_batch_pipeline(config)
