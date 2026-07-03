"""Node-level configuration for the Sparki pipeline."""

from dataclasses import dataclass


@dataclass
class NodeConfig:
    """Configuration for a single node's retry and execution behavior."""

    max_retries: int = 3          # Maximum retry attempts
    retry_delay: float = 5.0      # Base delay between retries (seconds)

    def __repr__(self) -> str:
        return f"NodeConfig(max_retries={self.max_retries}, retry_delay={self.retry_delay}s)"


# Node-specific configurations
NODE_CONFIGS: dict[str, NodeConfig] = {
    "initialize_node": NodeConfig(max_retries=3, retry_delay=5),
    "query_planner_node": NodeConfig(max_retries=3, retry_delay=5),
    "crawler_node": NodeConfig(max_retries=3, retry_delay=5),
    "worker_node": NodeConfig(max_retries=3, retry_delay=5),
    "router_node": NodeConfig(max_retries=1, retry_delay=1),  # Router doesn't retry
    "quality_scorer_node": NodeConfig(max_retries=3, retry_delay=5),
    "image_gen_node": NodeConfig(max_retries=3, retry_delay=5),
    "output_composer_node": NodeConfig(max_retries=2, retry_delay=3),
    "feedback_node": NodeConfig(max_retries=2, retry_delay=3),
}


def get_node_config(node_name: str) -> NodeConfig:
    """Get the configuration for a specific node."""
    return NODE_CONFIGS.get(node_name, NodeConfig())


__all__ = ["NodeConfig", "NODE_CONFIGS", "get_node_config"]