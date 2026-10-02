import asyncio
import json
import sys
import threading
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from pathlib import Path

from dotenv import load_dotenv
from langchain_mcp_adapters.tools import load_mcp_tools
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

from workflow import build_workflow


BASE_DIR = Path(__file__).resolve().parent

# Serialize operations in this app so separate MCP processes do not
# access the local Chroma directory at the same time.
BACKEND_LOCK = threading.Lock()


async def perform_request(action, payload):
    load_dotenv(BASE_DIR / ".env", override=True)

    server = StdioServerParameters(
        command=sys.executable,
        args=[str(BASE_DIR / "mcp_server.py")],
        cwd=str(BASE_DIR),
    )

    async with stdio_client(server) as (read, write):
        async with ClientSession(
            read,
            write,
            read_timeout_seconds=timedelta(seconds=180),
        ) as session:
            await session.initialize()

            if action == "chat":
                tools = await load_mcp_tools(session)
                workflow = build_workflow(tools)

                return await workflow.ainvoke(
                    payload,
                    config={"recursion_limit": 12},
                )

            if action not in {
                "ingest_policy_pdf",
                "list_policy_documents",
            }:
                raise ValueError("Unsupported application action.")

            result = await session.call_tool(
                action,
                arguments=payload,
            )

            if result.isError:
                # These administrative tools contain no API credentials.
                details = " ".join(
                    block.text
                    for block in result.content
                    if block.type == "text"
                )
                raise RuntimeError(details or "MCP tool failed.")

            if result.structuredContent is not None:
                return result.structuredContent

            for block in result.content:
                if block.type == "text":
                    return json.loads(block.text)

            raise RuntimeError("MCP returned no usable data.")


# Share one worker and event loop across all backend requests.
BACKEND_EXECUTOR = ThreadPoolExecutor(max_workers=1)
BACKEND_LOOP = None


def run_in_worker(action, payload):
    global BACKEND_LOOP

    if BACKEND_LOOP is None:
        if sys.platform == "win32":
            BACKEND_LOOP = asyncio.ProactorEventLoop()
        else:
            BACKEND_LOOP = asyncio.new_event_loop()

        asyncio.set_event_loop(BACKEND_LOOP)

    return BACKEND_LOOP.run_until_complete(
        asyncio.wait_for(
            perform_request(action, payload),
            timeout=300,
        )
    )


def run_backend(action, payload):
    with BACKEND_LOCK:
        future = BACKEND_EXECUTOR.submit(
            run_in_worker,
            action,
            payload,
        )
        return future.result()