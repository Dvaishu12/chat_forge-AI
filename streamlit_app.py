import hashlib
import os

import streamlit as st
from fastapi import HTTPException

from main import MAX_IMAGE_BYTES, answer_image_question, index_image

st.set_page_config(
    page_title="Framewise | Image intelligence",
    page_icon="F",
    layout="wide",
    initial_sidebar_state="expanded",
)

st.markdown(
    """
    <style>
      :root {
        --fw-ink: #1c2821;
        --fw-muted: #69766d;
        --fw-green: #3e7552;
        --fw-orange: #c96a46;
      }
      .stApp {
        background: radial-gradient(#dce5dc 0.65px, transparent 0.65px), #f1f4ef;
        background-size: 18px 18px;
        color: var(--fw-ink);
      }
      [data-testid="stSidebar"] {
        border-right: 1px solid #34493d;
        background: #1c3026;
      }
      [data-testid="stSidebar"] * { color: #f4f6f1; }
      [data-testid="stSidebar"] [data-testid="stMarkdownContainer"] p { color: #c7d1c8; }
      [data-testid="stSidebar"] hr { border-color: #405548; }
      .block-container { max-width: 1440px; padding-top: 2.2rem; padding-bottom: 3rem; }
      h1, h2, h3 { color: var(--fw-ink); letter-spacing: 0; }
      h1 { font-family: "Manrope", sans-serif; font-weight: 700; }
      [data-testid="stCaptionContainer"] { color: var(--fw-muted); }
      [data-testid="stFileUploader"] section {
        border: 1px dashed #b9cbbb;
        border-radius: 8px;
        background: #f8faf7;
      }
      [data-testid="stFileUploader"] section:hover { border-color: #68936d; }
      .stButton > button {
        min-height: 42px;
        border: 1px solid #dfe6df;
        border-radius: 6px;
        color: #40574a;
        background: #ffffff;
        transition: border-color 140ms ease, background 140ms ease;
      }
      .stButton > button:hover { border-color: #8dad91; color: #254832; background: #f4f8f3; }
      .stButton > button[kind="primary"] {
        border-color: var(--fw-green);
        color: #ffffff;
        background: var(--fw-green);
      }
      [data-testid="stChatInput"] textarea { font-size: 14px; }
      [data-testid="stMetric"] {
        padding: 12px 14px;
        border: 1px solid #dfe6df;
        border-radius: 7px;
        background: #ffffff;
      }
      @media (max-width: 700px) {
        .block-container { padding: 1.3rem 1rem 2rem; }
        h1 { font-size: 2rem; }
      }
    </style>
    """,
    unsafe_allow_html=True,
)


def initialize_state() -> None:
    defaults = {
        "image_digest": None,
        "attempted_digest": None,
        "image_bytes": None,
        "image_id": None,
        "filename": None,
        "extracted_text": None,
        "chunk_count": 0,
        "processing_error": None,
        "chat_history": [],
        "queued_question": None,
    }
    for key, value in defaults.items():
        if key not in st.session_state:
            st.session_state[key] = value


def process_upload(uploaded_file) -> None:
    image_bytes = uploaded_file.getvalue()
    digest = hashlib.sha256(image_bytes).hexdigest()
    if digest == st.session_state.image_digest or digest == st.session_state.attempted_digest:
        return

    st.session_state.attempted_digest = digest
    st.session_state.image_id = None
    st.session_state.image_digest = None
    st.session_state.image_bytes = image_bytes
    st.session_state.filename = uploaded_file.name
    st.session_state.extracted_text = None
    st.session_state.chat_history = []
    st.session_state.processing_error = None

    if len(image_bytes) > MAX_IMAGE_BYTES:
        st.session_state.processing_error = "Images must be smaller than 12 MB."
        return

    try:
        with st.status("Reading and indexing your image", expanded=False) as status:
            status.write("Enhancing the image and extracting its text.")
            result = index_image(image_bytes, uploaded_file.name)
            status.update(label="Image indexed and ready", state="complete")
        st.session_state.image_digest = digest
        st.session_state.image_id = result["image_id"]
        st.session_state.extracted_text = result["text"]
        st.session_state.chunk_count = result["chunk_count"]
    except HTTPException as error:
        st.session_state.processing_error = str(error.detail)
    except Exception as error:
        st.session_state.processing_error = f"Could not process this image: {error}"


def ask_question(question: str) -> None:
    question = question.strip()
    if not question or not st.session_state.image_id:
        return

    st.session_state.chat_history.append({"role": "user", "content": question})
    try:
        result = answer_image_question(st.session_state.image_id, question)
        st.session_state.chat_history.append(
            {
                "role": "assistant",
                "content": str(result["answer"]),
                "sources": result["sources"],
            }
        )
    except HTTPException as error:
        st.session_state.chat_history.append(
            {"role": "assistant", "content": str(error.detail), "sources": []}
        )
    except Exception as error:
        st.session_state.chat_history.append(
            {"role": "assistant", "content": f"Could not generate an answer: {error}", "sources": []}
        )


initialize_state()

with st.sidebar:
    st.title("framewise.")
    st.caption("IMAGE INTELLIGENCE WORKSPACE")
    st.divider()
    st.markdown("#### Your workflow")
    st.markdown("01  Upload a document image")
    st.markdown("02  Review the extracted text")
    st.markdown("03  Ask a grounded question")
    st.divider()
    if os.getenv("GROQ_API_KEY"):
        st.success("OCR + AI connected", icon=":material/check_circle:")
    else:
        st.warning("Add GROQ_API_KEY to .env for answers", icon="⚠️")
    st.caption("Your image is processed in this workspace.")

st.markdown("`IMAGE INTELLIGENCE  /  001`")
st.title("Your image, understood.")
st.caption("Extract what matters. Ask better questions.")
st.divider()

source_column, answer_column = st.columns([0.96, 1.04], gap="large")

with source_column:
    st.subheader("01  Your source")
    uploaded_file = st.file_uploader(
        "Choose or drop a document image",
        type=["png", "jpg", "jpeg", "webp", "tif", "tiff"],
        help="PNG, JPG, WEBP, or TIFF. Maximum size: 12 MB.",
    )

    if uploaded_file:
        process_upload(uploaded_file)
        if st.session_state.image_bytes:
            st.image(st.session_state.image_bytes, caption=st.session_state.filename, use_container_width=True)
        if st.session_state.processing_error:
            st.error(st.session_state.processing_error)
            if st.button("Retry image processing", key="retry_processing"):
                st.session_state.attempted_digest = None
                st.rerun()
        elif st.session_state.image_id:
            st.success("Image indexed and ready for questions.", icon=":material/task_alt:")
            metric_columns = st.columns(2)
            metric_columns[0].metric("Characters", f"{len(st.session_state.extracted_text):,}")
            metric_columns[1].metric("Searchable chunks", st.session_state.chunk_count)
            with st.expander("Review extracted text"):
                st.text_area(
                    "Extracted text",
                    value=st.session_state.extracted_text,
                    height=260,
                    label_visibility="collapsed",
                    disabled=True,
                )
    else:
        st.info("Upload a scan, screenshot, or photographed page to get started.")

with answer_column:
    st.subheader("02  Ask your image")
    if not st.session_state.image_id:
        st.markdown("### Bring the document into focus")
        st.write("Once the image is indexed, ask for a summary, a specific detail, or a connection between ideas.")
        st.caption("Answers are grounded in the text extracted from your image.")
    else:
        for message in st.session_state.chat_history:
            with st.chat_message(message["role"]):
                st.markdown(message["content"])
                if message.get("sources"):
                    with st.expander("Source excerpts"):
                        for source in message["sources"]:
                            st.markdown(f"> {source}")

        if not st.session_state.chat_history:
            st.markdown("#### Start with a question")
            suggestions = [
                "What is this document mainly about?",
                "Summarize the key points.",
                "What important details should I notice?",
            ]
            suggestion_columns = st.columns(3)
            for column, suggestion in zip(suggestion_columns, suggestions):
                if column.button(suggestion, key=f"suggestion_{suggestions.index(suggestion)}", use_container_width=True):
                    st.session_state.queued_question = suggestion
                    st.rerun()

        typed_question = st.chat_input("Ask anything about this image")
        question = typed_question or st.session_state.queued_question
        if question:
            st.session_state.queued_question = None
            with st.spinner("Searching the document and preparing an answer..."):
                ask_question(question)
            st.rerun()