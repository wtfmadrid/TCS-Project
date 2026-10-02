import hashlib
import re
import time
from pathlib import Path
import traceback

import streamlit as st

from app_backend import run_backend


BASE_DIR = Path(__file__).resolve().parent

st.set_page_config(
    page_title="SupportDesk AI",
    page_icon="💬",
    layout="wide",
)

if "messages" not in st.session_state:
    st.session_state.messages = []

if "policy_documents" not in st.session_state:
    st.session_state.policy_documents = None

if "upload_notice" not in st.session_state:
    st.session_state.upload_notice = None


def render_message(message):
    with st.chat_message(message["role"]):
        st.markdown(message["content"])

        if message["role"] != "assistant":
            return

        result = message.get("result")
        if not result:
            return

        st.caption(
            f"Route: {result.get('route', 'unknown')} · "
            f"{message.get('elapsed', 0):.1f} seconds"
        )

        with st.expander("Execution trace"):
            st.json(result.get("trace", []))

        customer_evidence = result.get("customer_evidence", [])
        policy_evidence = result.get("policy_evidence", [])

        if customer_evidence:
            with st.expander("Customer evidence"):
                st.json(customer_evidence)

        if policy_evidence:
            with st.expander("Retrieved policy passages"):
                st.json(policy_evidence)


with st.sidebar:
    st.header("Policy documents")
    st.caption("Upload a text-based PDF to make it searchable.")

    with st.form("policy_upload"):
        uploaded = st.file_uploader(
            "Policy PDF",
            type=["pdf"],
        )

        company = st.text_input(
            "Company",
            value="CompuSave",
        )

        version = st.text_input(
            "Policy version",
            value="June 2021",
        )

        submitted = st.form_submit_button("Index PDF")

    if submitted:
        st.session_state.upload_notice = None

        if uploaded is None:
            st.warning("Choose a PDF first.")
        elif not company.strip() or not version.strip():
            st.warning("Enter the company and policy version.")
        else:
            data = uploaded.getvalue()

            if len(data) > 10 * 1024 * 1024:
                st.error("Please use a PDF smaller than 10 MB.")
            else:
                # Preserve a readable filename while avoiding collisions.
                safe_name = re.sub(
                    r"[^A-Za-z0-9._-]",
                    "_",
                    uploaded.name,
                )[-120:]

                if not safe_name.lower().endswith(".pdf"):
                    safe_name += ".pdf"

                digest = hashlib.sha256(data).hexdigest()
                relative_path = Path("uploads") / digest / safe_name
                destination = BASE_DIR / "policies" / relative_path
                destination.parent.mkdir(parents=True, exist_ok=True)
                destination.write_bytes(data)

                try:
                    with st.spinner("Extracting and indexing PDF..."):
                        result = run_backend(
                            "ingest_policy_pdf",
                            {
                                "relative_path": relative_path.as_posix(),
                                "company": company,
                                "version": version,
                            },
                        )

                    if result["status"] == "already_indexed":
                        notice = (
                            "This PDF is already indexed. "
                            "No duplicate chunks were added."
                        )
                    else:
                        notice = (
                            f"Indexed {result['pages']} pages into "
                            f"{result['chunks']} chunks."
                        )

                    st.session_state.upload_notice = notice
                    st.session_state.policy_documents = None

                    if result.get("pages_without_text"):
                        st.warning(
                            "No text was extracted from pages: "
                            + str(result["pages_without_text"])
                        )

                except Exception as exc:
                    st.error(
                        f"Indexing failed ({type(exc).__name__}). "
                        "Check that the PDF contains selectable text "
                        "and the local embedding model is available."
                    )

    if st.session_state.upload_notice:
        st.success(st.session_state.upload_notice)

    if st.button("Show / refresh indexed policies"):
        try:
            with st.spinner("Loading document list..."):
                result = run_backend("list_policy_documents", {})
            st.session_state.policy_documents = result["documents"]
        except Exception as exc:
            st.error(f"Could not load documents: {type(exc).__name__}")

    documents = st.session_state.policy_documents

    if documents is not None:
        if not documents:
            st.info("No policies indexed yet.")

        for document in documents:
            st.write(document["filename"])
            st.caption(
                f"{document['company']} · {document['version']} · "
                f"{document['chunks']} chunks"
            )

    st.divider()

    if st.button("Clear conversation"):
        st.session_state.messages = []
        st.rerun()


st.title("SupportDesk AI")
st.write("Investigate customer cases and find answers in company policies.")

st.caption(
    "Demo: synthetic customer records, snapshot 2026-10-01. "
    "Public policy documents are reference material. "
    "The assistant provides guidance and cannot issue refunds."
)

if not st.session_state.messages:
    st.info(
        "Try: “Summarize Ema Wilson’s support history” or "
        "“What evidence is required for shipping damage?”"
    )


chat_area = st.container(key="conversation")

with chat_area:
    for index, message in enumerate(st.session_state.messages):
        with st.container(key=f"message_{index}"):
            render_message(message)

question = st.chat_input(
    "Ask about a customer, support ticket, or uploaded policy"
)

if question and question.strip():
    question = question.strip()

    history = [
        {"role": message["role"], "content": message["content"]}
        for message in st.session_state.messages
    ]

    next_index = len(st.session_state.messages)
    user_message = {"role": "user", "content": question}
    completed = False

    with chat_area:
        with st.container(key=f"message_{next_index}"):
            with st.empty().container():
                render_message(user_message)

        with st.container(key=f"message_{next_index + 1}"):
            response_area = st.empty()

            with response_area.container():
                with st.chat_message("assistant"):
                    started = time.perf_counter()

                    try:
                        with st.spinner(
                            "Reviewing the relevant information..."
                        ):
                            result = run_backend(
                                "chat",
                                {
                                    "question": question,
                                    "history": history,
                                },
                            )

                        assistant_message = {
                            "role": "assistant",
                            "content": result["answer"],
                            "result": result,
                            "elapsed": time.perf_counter() - started,
                        }

                        st.session_state.messages.extend([
                            user_message,
                            assistant_message,
                        ])

                        completed = True

                    except Exception as exc:
                        st.error(
                            f"Request failed ({type(exc).__name__}). "
                            "Your previous conversation is preserved."
                        )

                        error_details = traceback.format_exc()
                        print(error_details)

                        with st.expander("Error details", expanded=True):
                            st.code(error_details, language="text")

    if completed:
        # Render the completed turn from the same history structure
        # used for every other message.
        response_area.empty()
        st.rerun()