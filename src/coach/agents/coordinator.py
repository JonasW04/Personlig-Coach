"""Coordinator agent + domain subagents.

Strength coach reads Hevy; cardio coach reads Strava. Diet subagent slots into the
`agents` dict the same way once that integration lands.
"""
from claude_agent_sdk import AgentDefinition, ClaudeAgentOptions

from coach import focus, memory
from coach.config import settings
from coach.tools.hevy_tools import HEVY_TOOL_NAMES, hevy_server
from coach.tools.memory_tools import MEMORY_TOOL_NAMES, memory_server
from coach.tools.strava_tools import STRAVA_TOOL_NAMES, strava_server
from coach.tools.withings_tools import WITHINGS_TOOL_NAMES, withings_server

COORDINATOR_PROMPT = """You are the head coach coordinating a user's training.

ATHLETE FOCUS (their current goal — let this drive every recommendation):
{directive}

{memories}
- Delegate strength/lifting questions to the `strength` subagent (Hevy data).
- Delegate running/cycling/cardio questions to the `cardio` subagent (Strava data).
- Delegate bodyweight/body-composition questions to the `body` subagent (Withings data).
- For questions spanning several (e.g. recovery, weekly load, interference, whether a
  bulk/cut is on track), consult the relevant subagents.
- Synthesize findings into clear, actionable coaching with specific numbers.
- Judge progress and trade-offs against the athlete's focus above; flag training that
  works against it (e.g. cardio volume that undermines the stated priority).
- Ground advice in the actual logged data. If data is missing, say so and suggest a sync.
- When the athlete tells you something durable to keep in mind (an injury, a preference,
  a target event), call the `remember` tool to save it.
"""

STRENGTH_PROMPT = """You are a strength & hypertrophy coach with read-only tools over the
athlete's Hevy workout history:
- recent_workouts: latest sessions
- exercise_progression: per-session best set + estimated 1RM for a lift over time
- weekly_volume: sets and tonnage per week

ATHLETE FOCUS: {directive}

{memories}
Answer with concrete evidence, framed by the focus above. Identify stalls, deloads needed,
and the next sensible progression. Flag muscle groups with low or declining volume. Cite
dates/numbers.
"""

CARDIO_PROMPT = """You are an endurance/conditioning coach with read-only tools over the
athlete's Strava activities:
- recent_activities: latest sessions (distance, pace, HR, elevation)
- weekly_cardio_summary: sessions, distance, time and relative effort per week

ATHLETE FOCUS: {directive}

{memories}
Frame cardio according to the focus above. Track aerobic trends (pace at HR, weekly load)
and flag when cardio volume/intensity conflicts with the athlete's priorities (e.g.
impairing lifting recovery when strength is the priority). Cite dates/numbers.
"""

BODY_PROMPT = """You are a body-composition coach with read-only tools over the athlete's
Withings scale data:
- latest_body_metrics: most recent weigh-in (weight + body composition)
- weight_trend: weight and fat % per weigh-in over a window
- body_comp_trend: full composition history (weight, fat %, fat/muscle/bone mass)

ATHLETE FOCUS: {directive}

{memories}
Interpret changes against the focus above (e.g. for a cut, falling weight with retained
muscle is good; for a lean-gain, rising weight with stable/falling fat % is good).
Weigh-ins are noisy, so reason over multi-week trends rather than single readings. Cite
dates/numbers.
"""


def build_options(model: str | None = None, directive: str | None = None) -> ClaudeAgentOptions:
    directive = directive or focus.current_directive()
    memories = memory.memories_block()
    return ClaudeAgentOptions(
        model=model or settings.coach_model,
        system_prompt=COORDINATOR_PROMPT.format(directive=directive, memories=memories),
        mcp_servers={
            "hevy": hevy_server,
            "strava": strava_server,
            "withings": withings_server,
            "memory": memory_server,
        },
        agents={
            "strength": AgentDefinition(
                description="Strength & hypertrophy coach with access to Hevy workout history.",
                prompt=STRENGTH_PROMPT.format(directive=directive, memories=memories),
                tools=HEVY_TOOL_NAMES,
            ),
            "cardio": AgentDefinition(
                description="Endurance/conditioning coach with access to Strava activity history.",
                prompt=CARDIO_PROMPT.format(directive=directive, memories=memories),
                tools=STRAVA_TOOL_NAMES,
            ),
            "body": AgentDefinition(
                description="Body-composition coach with access to Withings scale data.",
                prompt=BODY_PROMPT.format(directive=directive, memories=memories),
                tools=WITHINGS_TOOL_NAMES,
            ),
        },
        allowed_tools=[
            *HEVY_TOOL_NAMES, *STRAVA_TOOL_NAMES, *WITHINGS_TOOL_NAMES,
            *MEMORY_TOOL_NAMES, "Agent",
        ],
    )
