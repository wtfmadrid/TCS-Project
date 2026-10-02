import asyncio
import json
from datetime import timedelta
from pathlib import Path
import sys

from dotenv import load_dotenv
from langchain_mcp_adapters.tools import load_mcp_tools
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

from workflow import build_workflow


BASE_DIR = Path(__file__).resolve().parent


async def main():
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
            read_timeout_seconds=timedelta(seconds=120),
        ) as session:
            await session.initialize()
            tools = await load_mcp_tools(session)
            workflow = build_workflow(tools)

            history = []
            last_result = None

            print("\nSupport assistant ready.")
            print("Commands: reset, evidence, exit\n")

            while True:
                question = (
                    await asyncio.to_thread(input, "You: ")
                ).strip()

                if question.lower() == "exit":
                    break

                if question.lower() == "reset":
                    history = []
                    last_result = None
                    print("Conversation cleared.\n")
                    continue

                if question.lower() == "evidence":
                    if last_result is None:
                        print("No completed question yet.\n")
                    else:
                        print(json.dumps({
                            "customer": last_result.get(
                                "customer_evidence", []
                            ),
                            "policy": last_result.get(
                                "policy_evidence", []
                            ),
                        }, indent=2, ensure_ascii=False))
                    continue

                if not question:
                    continue

                try:
                    result = await workflow.ainvoke(
                        {
                            "question": question,
                            "history": history,
                        },
                        config={"recursion_limit": 12},
                    )
                except Exception as exc:
                    print(f"\nRequest failed: {type(exc).__name__}")
                    print("Previous conversation preserved.\n")
                    continue

                last_result = result

                print("\nExecution trace:")
                for step in result["trace"]:
                    print(json.dumps(step, ensure_ascii=False))

                print(f"\nAssistant: {result['answer']}\n")

                history.extend([
                    {"role": "user", "content": question},
                    {"role": "assistant", "content": result["answer"]},
                ])


if __name__ == "__main__":
    asyncio.run(main())