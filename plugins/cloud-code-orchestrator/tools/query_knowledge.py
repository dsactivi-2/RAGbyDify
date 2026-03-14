import httpx
from dify_plugin import Tool
from dify_plugin.entities.tool import ToolInvokeMessage

class QueryKnowledgeTool(Tool):
    def _invoke(self, tool_parameters: dict) -> list[ToolInvokeMessage]:
        url = self.runtime.credentials.get('orchestrator_url', 'http://host.docker.internal:8000')
        query = tool_parameters.get('query', '')
        hop_depth = int(tool_parameters.get('hop_depth', 2))
        try:
            resp = httpx.post(f'{url}/hipporag/query', json={
                'query': query, 'hop_depth': hop_depth, 'limit': 10
            }, timeout=15.0)
            data = resp.json()
            results = data.get('results', [])
            if not results:
                return [self.create_text_message(f'No knowledge found for: {query}')]
            lines = []
            for r in results:
                for rel in r.get('relationships', []):
                    lines.append(f"{rel['from']} --[{rel['type']}]--> {rel['to']}")
            return [self.create_text_message('\n'.join(lines) if lines else 'No relationships found')]
        except Exception as e:
            return [self.create_text_message(f'KG query error: {e}')]
