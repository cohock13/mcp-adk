from google.adk.agents import Agent
from dotenv import load_dotenv
import os
from .tools import *

load_dotenv()
model = os.getenv("AGENT_MODEL", "gemini-2.5-flash")

root_agent = Agent(
    name="weather_time_agent",
    model=model,
    description=(
        "Agent to answer questions about the time and weather in a city."
    ),
    instruction=(
        "You are a helpful agent who can answer user questions about the time and weather in a city."
    ),
    tools=[get_weather, get_current_time],
)