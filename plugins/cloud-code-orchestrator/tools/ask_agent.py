import json
import httpx
from dify_plugin import Tool
from dify_plugin.entities.tool import ToolInvokeMessage

class AskAgentTool(Tool):
    def _invoke(self, tool_parameters: dict) -> list[ToolInvokeMessage]:
        url = self.runtime.credentials.get('orchestrator_url', 'http://host.docker.internal:8000')
        agent = tool_parameters.get('agent', 'worker')
        query = tool_parameters.get('query', '')
        user = tool_parameters.get('user', 'dify-plugin')
        try:
            resp = httpx.post(f'{url}/task', json={
                'agent': agent, 'query': query, 'user': user
            }, timeout=60.0)
            data = resp.json()
            answer = data.get('answer', 'No response')
            sources = data.get('sources', {})
            result = f"""Agent: {agent}
Answer: {answer}
KB Hits: {sources.get('kb_hits', 0)}
Memory: {sources.get('memory', False)}
Confidence: {sources.get('confidence', 'unknown')}"""
            return [self.create_text_message(result)]
        except Exception as e:
            return [self.create_text_message(f'Error calling agent {agent}: {e}')]
