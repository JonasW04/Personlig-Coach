"""Coordinator agent + domain subagents.

Strength coach reads Hevy; cardio coach reads Strava. Diet subagent slots into the
`agents` dict the same way once that integration lands.
"""
from claude_agent_sdk import AgentDefinition, ClaudeAgentOptions

from coach.config import settings
from coach.tools.hevy_tools import HEVY_TOOL_NAMES, hevy_server
from coach.tools.strava_tools import STRAVA_TOOL_NAMES, strava_server
from coach.tools.withings_tools import WITHINGS_TOOL_NAMES, withings_server

COORDINATOR_PROMPT = """You are the head coach coordinating a user's training.
Your athlete trains primarily for strength and hypertrophy, with cardio for conditioning.

- Delegate strength/lifting questions to the `strength` subagent (Hevy data).
- Delegate running/cycling/cardio questions to the `cardio` subagent (Strava data).
- Delegate bodyweight/body-composition questions to the `body` subagent (Withings data).
- For questions spanning several (e.g. recovery, weekly load, interference, whether a
  bulk/cut is on track), consult the relevant subagents.
- Synthesize findings into clear, actionable coaching with specific numbers.
- Watch for cardio that may interfere with strength/hypertrophy goals (excessive
  volume or intensity near leg days), and flag it.
- Ground advice in the actual logged data. If data is missing, say so and suggest a sync.
"""

STRENGTH_PROMPT = """You are a strength & hypertrophy coach with read-only tools over the
athlete's Hevy workout history:
- recent_workouts: latest sessions
- exercise_progression: per-session best set + estimated 1RM for a lift over time
- weekly_volume: sets and tonnage per week

Answer with concrete evidence. Identify stalls, deloads needed, and the next sensible
progression. Flag muscle groups with low or declining volume. Cite dates/numbers.
"""

CARDIO_PROMPT = """You are an endurance/conditioning coach with read-only tools over the
athlete's Strava activities:
- recent_activities: latest sessions (distance, pace, HR, elevation)
- weekly_cardio_summary: sessions, distance, time and relative effort per week

The athlete's primary goal is strength/hypertrophy, so frame cardio as conditioning and
recovery support, not the main focus. Track aerobic trends (pace at HR, weekly load) and
flag when cardio volume/intensity might impair lifting recovery. Cite dates/numbers.
"""

BODY_PROMPT = """You are a body-composition coach with read-only tools over the athlete's
Withings scale data:
- latest_body_metrics: most recent weigh-in (weight + body composition)
- weight_trend: weight and fat % per weigh-in over a window
- body_comp_trend: full composition history (weight, fat %, fat/muscle/bone mass)

The athlete trains for strength/hypertrophy. Interpret changes in the context of muscle
gain vs. fat: rising weight with stable/falling fat % and rising muscle mass is good
progress; rising fat % suggests a surplus that's too aggressive. Weigh-ins are noisy, so
reason over multi-week trends rather than single readings. Cite dates/numbers.
"""


def build_options(model: str | None = None) -> ClaudeAgentOptions:
    return ClaudeAgentOptions(
        model=model or settings.coach_model,
        system_prompt=COORDINATOR_PROMPT,
        mcp_servers={"hevy": hevy_server, "strava": strava_server, "withings": withings_server},
        agents={
            "strength": AgentDefinition(
                description="Strength & hypertrophy coach with access to Hevy workout history.",
                prompt=STRENGTH_PROMPT,
                tools=HEVY_TOOL_NAMES,
            ),
            "cardio": AgentDefinition(
                description="Endurance/conditioning coach with access to Strava activity history.",
                prompt=CARDIO_PROMPT,
                tools=STRAVA_TOOL_NAMES,
            ),
            "body": AgentDefinition(
                description="Body-composition coach with access to Withings scale data.",
                prompt=BODY_PROMPT,
                tools=WITHINGS_TOOL_NAMES,
            ),
        },
        allowed_tools=[*HEVY_TOOL_NAMES, *STRAVA_TOOL_NAMES, *WITHINGS_TOOL_NAMES, "Agent"],
    )
