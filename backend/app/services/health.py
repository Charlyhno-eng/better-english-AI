class HealthService:
    def status(self) -> str:
        """Process liveness only; does not load or probe AI models."""
        return "ok"
