from google.adk.agents import SequentialAgent

from mobile_agents.static_agent.init_agent import init_agent

mobile_static_analysis_agent = SequentialAgent(
    name="MobileStaticAnalysisAgent",
    description="Run WCAG static analysis on mobile snapshots.",
    sub_agents=[init_agent],
)
