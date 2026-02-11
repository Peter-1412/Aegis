from __future__ import annotations

from langchain.agents import AgentExecutor
from langchain.agents.output_parsers import ReActSingleInputOutputParser
from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.prompts import ChatPromptTemplate, MessagesPlaceholder
from langchain.memory import ConversationBufferMemory
from langchain_core.agents import AgentAction, AgentFinish
from langchain_core.runnables import RunnablePassthrough
from langchain.agents.format_scratchpad import format_log_to_str
from langchain.tools.render import render_text_description

from app.prompt.ops_prompts import OPS_SYSTEM_PROMPT
from config.config import settings

try:
    from langchain.agents import create_react_agent as _create_agent
except Exception:
    from langchain.agents import create_tool_calling_agent as _create_agent


class LoggingReActOutputParser(ReActSingleInputOutputParser):
    def parse(self, text: str) -> AgentAction | AgentFinish:
        try:
            # Handle non-standard "Final:" instead of "Final Answer:" if model gets it wrong
            if "Final Answer:" not in text and "Final:" in text:
                text = text.replace("Final:", "Final Answer:")
            
            # Truncate hallucinated observations to prevent "both final answer and action" error
            if "Observation:" in text:
                text = text.split("Observation:")[0].strip()
            
            result = super().parse(text)
            
            # Clean up tool_input if it's a string containing Markdown JSON
            if isinstance(result, AgentAction) and isinstance(result.tool_input, str):
                cleaned_input = result.tool_input.strip()
                if cleaned_input.startswith("```"):
                    cleaned_input = cleaned_input.strip("`")
                    if cleaned_input.startswith("json"):
                        cleaned_input = cleaned_input[4:]
                    cleaned_input = cleaned_input.strip()
                    # Re-assign the cleaned input (AgentAction is a named tuple, need to replace)
                    result = AgentAction(tool=result.tool, tool_input=cleaned_input, log=result.log)
            
            return result
        except Exception:
            # Try to fix common JSON errors (e.g. double output) before giving up
            if "}{" in text:
                text = text.split("}{")[0] + "}"
            try:
                return super().parse(text)
            except Exception as e:
                import logging
                logging.warning("ReAct parse failed: %s, text_len=%s, content=%r", e, len(text), text)
                raise


def build_executor(llm: BaseChatModel, tools, memory: ConversationBufferMemory | None) -> AgentExecutor:
    prompt = ChatPromptTemplate.from_messages(
        [
            ("system", OPS_SYSTEM_PROMPT),
            MessagesPlaceholder(variable_name="chat_history"),
            ("human", "{input}"),
            ("assistant", "{agent_scratchpad}"),
        ]
    ).partial(
        tools=render_text_description(tools),
        tool_names=", ".join([t.name for t in tools]),
    )

    # Manually construct agent to inject custom parser
    agent = (
        RunnablePassthrough.assign(
            agent_scratchpad=lambda x: format_log_to_str(x["intermediate_steps"]),
        )
        | prompt
        | llm.bind(stop=["\nObservation"])
        | LoggingReActOutputParser()
    )
    
    return AgentExecutor(
        agent=agent,
        tools=tools,
        memory=memory,
        verbose=True,
        handle_parsing_errors=True,
        return_intermediate_steps=True,
        max_iterations=settings.agent_max_iterations,
        max_execution_time=settings.agent_max_execution_time_s,
    )

