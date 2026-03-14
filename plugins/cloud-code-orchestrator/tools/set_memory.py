import json
import httpx
from dify_plugin import Tool
from dify_plugin.entities.tool import ToolInvokeMessage

class SetMemoryTool(Tool):
    def _invoke(self, tool_parameters: dict) -> list[ToolInvokeMessage]:
        url = self.runtime.credentials.get('orchestrator_url', 'http://host.docker.internal:8000')
        scope = tool_parameters.get('scope', 'system')
        key = tool_parameters.get('key', '')
        value = tool_parameters.get('value', '')
        agent_name = tool_parameters.get('agent_name', '')
        try:
            if scope == 'system':
                resp = httpx.put(f'{url}/memory/system/{key}', json={
                    'value': value, 'category': 'plugin', 'updated_by': 'dify-plugin'
                }, timeout=5.0)
            else:
                resp = httpx.post(f'{url}/memory/agent/{agent_name}', json={
                    'key': key, 'value': value
                }, timeout=5.0)
            return [self.create_text_message(f'Memory set: {scope}/{key} = {value[:100]}')]
        except Exception as e:
            return [self.create_text_message(f'Memory write error: {e}')]
