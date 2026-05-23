# Integration example

from memoryx.config import get_settings
from memoryx.logging import configure_logging, get_logger
from memoryx.manager import MemoryHookManager
from memoryx.events import MemoryEventType


async def print_handler(event):
    print(event.model_dump())


async def main():
    settings = get_settings()
    configure_logging(settings.logs_dir, settings.log_level)
    logger = get_logger("memoryx.example")
    manager = MemoryHookManager(settings=settings, logger=logger)
    await manager.register_handler(MemoryEventType.ON_USER_MESSAGE, print_handler)
    await manager.start()
    await manager.emit(MemoryEventType.ON_USER_MESSAGE, "session-1", {"content": "hello"})
    await manager.stop()
