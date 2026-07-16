"""Discovery prompts."""
from __future__ import annotations

from mcp.types import (
    GetPromptResult, Prompt, PromptArgument, PromptMessage, TextContent,
)

from .registry import register_prompt


_PROMPT = Prompt(
    name="discover_tables_for_business_question",
    description=(
        "Translate a natural-language question into the shortest discovery "
        "chain — candidates → describe → join path."
    ),
    arguments=[
        PromptArgument(
            name="goal",
            description="Free-form business question.",
            required=True,
        ),
    ],
)


_BODY = """You have a business question but not the target tables. Follow the discovery chain:

1. `discover_relevant_tables(goal={goal!r})` — returns a small ranked candidate set.
2. For the top 2–3 candidates, call `describe_table(detail="brief")` only. Skip "full" until you must.
3. If the question joins concepts, call `find_join_path` with `score=true` for each plausible pair to pick the best.
4. When you are confident, draft SQL and call `plan_or_execute_query` with mode="auto".

Keep each step's detail level at "brief" unless the prior step surfaced ambiguity.

Question: {goal}
"""


async def _handler(arguments: dict) -> GetPromptResult:
    goal = arguments.get("goal", "")
    text = _BODY.format(goal=goal)
    return GetPromptResult(
        description="Discovery chain for unknown tables.",
        messages=[
            PromptMessage(
                role="user",
                content=TextContent(type="text", text=text),
            ),
        ],
    )


def register() -> None:
    register_prompt(_PROMPT, _handler)
