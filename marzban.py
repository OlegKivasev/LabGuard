import httpx


class MarzbanClient:
    def __init__(self, base_url: str, api_key: str) -> None:
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key

    @property
    def is_configured(self) -> bool:
        return bool(self.base_url and self.api_key)

    async def healthcheck(self) -> bool:
        if not self.is_configured:
            return False

        headers = {"Authorization": f"Bearer {self.api_key}"}
        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.get(f"{self.base_url}/api/admin", headers=headers)
            return response.status_code < 400
