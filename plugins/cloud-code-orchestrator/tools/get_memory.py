import json
import httpx
from dify_plugin import Tool
from dify_plugin.entities.tool import ToolInvokeMessage

class GetMemoryTool(Tool):
    def _invoke(self, tool_parameters: dict) -> list[ToolInvokeMessage]:
        url = self.runtime.credentials.get('orchestrator_url', 'http://host.docker.internal:8000')
        scope = tool_parameters.get('scope', 'system')
        key = tool_parameters.get('key', '')
        agent_name = tool_parameters.get('agent_name', '')
        try:
            if scope == 'system':
                if key:
                    resp = httpx.get(f'{url}/memory/system/{key}', timeout=5.0)
                else:
                    resp = httpx.get(f'{url}/memory/system', timeout=5.0)
            else:
                resp = httpx.get(f'{url}/memory/agent/{agent_name}', timeout=5.0)
            data = resp.json()
            return [self.create_text_message(json.dumps(data, indent=2, ensure_ascii=False))]
        except Exception as e:
            return [self.create_text_message(f'Memory read error: {e}')]
