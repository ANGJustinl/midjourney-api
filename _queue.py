import asyncio
from collections import deque
from typing import Dict, Any, Callable, ParamSpec, Deque, List
from loguru import logger

P = ParamSpec("P")

class QueueFullError(Exception):
    pass

class Task:
    def __init__(
        self, func: Callable[P, Any], *args: P.args, **kwargs: P.kwargs
    ) -> None:
        self.func = func
        self.args = args
        self.kwargs = kwargs

    async def __call__(self) -> None:
        await self.func(*self.args, **self.kwargs)

    def __repr__(self) -> str:
        return f"{self.func.__name__}({self.args}, {self.kwargs})"

class TaskQueue:
    def __init__(self, concur_size: int = 9999, wait_size: int = 9999) -> None:
        """Initialize task queue
        
        Args:
            concur_size: Maximum number of concurrent tasks
            wait_size: Maximum size of waiting queue
        """
        self._concur_size = concur_size
        self._wait_size = wait_size
        self._wait_queue: Deque[Dict[str, Task]] = deque()
        self._concur_queue: List[str] = []

    def put(
            self,
            trigger_id: str,
            func: Callable[P, Any],
            *args: P.args,
            **kwargs: P.kwargs
    ) -> None:
        """Add task to queue
        
        Args:
            trigger_id: Unique identifier for the task
            func: Function to execute
            args: Positional arguments for the function
            kwargs: Keyword arguments for the function
            
        Raises:
            QueueFullError: If waiting queue is full
        """
        if len(self._wait_queue) >= self._wait_size:
            raise QueueFullError(f"Task queue is full: {self._wait_size}")

        self._wait_queue.append({
            trigger_id: Task(func, *args, **kwargs)
        })
        
        # Execute tasks if there's room in concurrent queue
        while self._wait_queue and len(self._concur_queue) < self._concur_size:
            self._exec()

    def pop(self, trigger_id: str) -> None:
        """Remove task from concurrent queue and execute next waiting task
        
        Args:
            trigger_id: ID of task to remove
        """
        if trigger_id in self._concur_queue:
            self._concur_queue.remove(trigger_id)
            if self._wait_queue:
                self._exec()

    def _exec(self):
        """Execute next task from waiting queue"""
        key, task = self._wait_queue.popleft().popitem()
        self._concur_queue.append(key)

        logger.debug(f"Task[{key}] start execution: {task}")
        loop = asyncio.get_running_loop()
        loop.create_task(task())

    @property
    def concur_size(self) -> int:
        """Get maximum concurrent tasks size"""
        return self._concur_size

    @property 
    def wait_size(self) -> int:
        """Get maximum waiting queue size"""
        return self._wait_size

    def clear(self) -> None:
        """Clear both waiting and concurrent queues"""
        self._wait_queue.clear()
        self._concur_queue.clear()

# Global task queue instance
taskqueue = TaskQueue()