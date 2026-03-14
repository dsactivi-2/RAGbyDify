import httpx
from dify_plugin import ToolProvider
from dify_plugin.errors.model import CredentialsValidateFailedError

class CloudCodeProvider(ToolProvider):
    def _validate_credentials(self, credentials: dict) -> None:
        url = credentials.get('orchestrator_url', 'http://host.docker.internal:8000')
        try:
            resp = httpx.get(f'{url}/health', timeout=5.0)
            if resp.status_code != 200:
                raise CredentialsValidateFailedError('Orchestrator not healthy')
        except Exception as e:
            raise CredentialsValidateFailedError(f'Cannot reach Orchestrator: {e}')
