from . import (
    metadata, policy, query, cache,
    relationship, object_tool, semantic, metrics,
)  # noqa: F401


_GROUP_REGISTRATIONS = {
    "metadata":     metadata.register,
    "policy":       policy.register,
    "query":        query.register,
    "cache":        cache.register,
    "relationship": relationship.register,
    "object":       object_tool.register,
    "semantic":     semantic.register,
    "metrics":      metrics.register,
}


def _resolve_profile_groups(profile: str) -> list[str]:
    if not profile or profile == "all":
        return list(_GROUP_REGISTRATIONS.keys())
    requested = [g.strip() for g in profile.split(",") if g.strip()]
    if not requested:
        return list(_GROUP_REGISTRATIONS.keys())
    unknown = [g for g in requested if g not in _GROUP_REGISTRATIONS]
    if unknown:
        raise ValueError(
            f"Unknown tool profile group(s): {', '.join(unknown)}. "
            f"Valid groups: {', '.join(sorted(_GROUP_REGISTRATIONS.keys()))}"
        )
    return requested


def register_all() -> None:
    from ...config import get_config
    cfg = get_config()
    for group in _resolve_profile_groups(cfg.tool_profile):
        _GROUP_REGISTRATIONS[group]()
