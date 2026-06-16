from coach.tools.hevy_tools import HEVY_TOOLS
from coach.tools.memory_tools import MEMORY_TOOLS
from coach.tools.strava_tools import STRAVA_TOOLS
from coach.tools.withings_tools import WITHINGS_TOOLS

ALL_TOOLS = [
    *HEVY_TOOLS,
    *STRAVA_TOOLS,
    *WITHINGS_TOOLS,
    *MEMORY_TOOLS,
]

TOOL_BY_NAME = {tool.name: tool for tool in ALL_TOOLS}
