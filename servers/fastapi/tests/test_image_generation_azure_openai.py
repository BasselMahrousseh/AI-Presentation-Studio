import base64
import os
from unittest.mock import AsyncMock, Mock, patch

import pytest

from services.image_generation_service import ImageGenerationService


class TestImageGenerationAzureOpenAI:
    @pytest.fixture
    def anyio_backend(self):
        return "asyncio"

    @pytest.mark.anyio
    async def test_generates_image_with_azure_deployment(self, tmp_path):
        output_directory = str(tmp_path)
        service = ImageGenerationService(output_directory)
        image = "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNkYAAAAAYAAjCB0C8AAAAASUVORK5CYII="

        with patch(
            "services.image_generation_service.get_azure_openai_image_endpoint_env",
            return_value="https://example.openai.azure.com",
        ), patch(
            "services.image_generation_service.get_azure_openai_image_api_key_env",
            return_value="test-key",
        ), patch(
            "services.image_generation_service.get_azure_openai_image_api_version_env",
            return_value="2024-02-01",
        ), patch(
            "services.image_generation_service.get_azure_openai_image_deployment_env",
            return_value="gpt-image-2",
        ), patch("services.image_generation_service.AsyncAzureOpenAI") as client_cls:
            client = client_cls.return_value
            result = Mock()
            item = Mock(b64_json=image, url=None)
            result.data = [item]
            client.images.generate = AsyncMock(return_value=result)

            image_path = await service.generate_image_azure_openai(
                "test prompt", output_directory
            )

        client_cls.assert_called_once_with(
            azure_endpoint="https://example.openai.azure.com",
            api_version="2024-02-01",
            api_key="test-key",
        )
        client.images.generate.assert_awaited_once_with(
            model="gpt-image-2", prompt="test prompt", n=1, size="1024x1024"
        )
        with open(image_path, "rb") as file:
            assert file.read() == base64.b64decode(image)
        assert os.path.exists(image_path)

    @pytest.mark.anyio
    async def test_requires_all_azure_image_settings(self, tmp_path):
        service = ImageGenerationService(str(tmp_path))
        with patch(
            "services.image_generation_service.get_azure_openai_image_endpoint_env",
            return_value=None,
        ):
            with pytest.raises(ValueError, match="AZURE_OPENAI_IMAGE_ENDPOINT"):
                await service.generate_image_azure_openai("test prompt", str(tmp_path))
