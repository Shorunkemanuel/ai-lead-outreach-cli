from dataclasses import dataclass
from typing import Dict, List


@dataclass(frozen=True)
class DeliveryResult:
    success: bool
    provider: str
    channel: str
    detail: str


class MessagingProvider:
    name = "base"
    channel = "unknown"

    def send(self, recipient: str, message: str) -> DeliveryResult:
        raise NotImplementedError


class MockEmailProvider(MessagingProvider):
    name = "mock_email"
    channel = "email"

    def send(self, recipient: str, message: str) -> DeliveryResult:
        return DeliveryResult(
            success=True,
            provider=self.name,
            channel=self.channel,
            detail=f"Mock email sent to {recipient}",
        )


class MockWhatsAppProvider(MessagingProvider):
    name = "mock_whatsapp"
    channel = "whatsapp"

    def send(self, recipient: str, message: str) -> DeliveryResult:
        return DeliveryResult(
            success=True,
            provider=self.name,
            channel=self.channel,
            detail=f"Mock WhatsApp message sent to {recipient}",
        )


class MessagingRegistry:
    def __init__(self):
        self._providers: Dict[str, MessagingProvider] = {}

    def register(self, provider: MessagingProvider) -> None:
        key = f"{provider.channel}:{provider.name}"
        self._providers[key] = provider

    def get(self, channel: str, provider: str) -> MessagingProvider:
        key = f"{channel}:{provider}"
        try:
            return self._providers[key]
        except KeyError:
            raise ValueError(
                f"Unsupported messaging provider: {channel}/{provider}"
            )

    def providers_for_channel(self, channel: str) -> List[str]:
        return sorted(
            provider.name
            for provider in self._providers.values()
            if provider.channel == channel
        )


def default_registry() -> MessagingRegistry:
    registry = MessagingRegistry()
    registry.register(MockEmailProvider())
    registry.register(MockWhatsAppProvider())
    return registry


# Convenience API used by the M4 queue layer.
def is_supported_provider(provider: str, channel: str) -> bool:
    """Return True when the provider is registered for the requested channel."""
    try:
        default_registry().get(channel, provider)
        return True
    except ValueError:
        return False


def get_provider(provider: str, channel: str) -> MessagingProvider:
    """Return a registered provider for a channel."""
    return default_registry().get(channel, provider)
