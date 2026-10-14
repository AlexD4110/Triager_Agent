"""Review page for the real labeled set. Shows only de-identified text, never the original message.

Check each example for anything that could identify a person (names, places, handles, order details) and
edit it out before approving. Only approved examples are ever used to score the classifier.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

import streamlit as st  # noqa: E402

from app import queue, realset  # noqa: E402
from app.store import connect  # noqa: E402
from triage.config import load_dotenv  # noqa: E402

load_dotenv()
st.set_page_config(page_title="Real set review", layout="wide")
st.title("Real labeled set: review")
st.caption("De-identified examples built from corrections. Approve only text with nothing that could identify "
           "a person. Residual warnings point at words that may be names or leftover digits.")

who = st.sidebar.text_input("Your name (saved with each review)", value="")

try:
    with connect() as conn:
        counts, rows = realset.status_counts(conn), realset.pending(conn)
except Exception as exc:
    st.error(f"Could not load the set: {type(exc).__name__}. Run sql/realset.sql in Supabase first.")
    st.stop()

cols = st.columns(4)
for col, status in zip(cols, ["pending_review", "approved", "rejected"]):
    col.metric(status.replace("_", " "), counts.get(status, 0))
cols[3].metric("Needed for stable scores", realset.MIN_ROWS_FOR_STABLE_SCORE)

if st.button("Build candidates from new corrections"):
    with connect() as conn:
        result = realset.build_candidates(conn)
    st.success(f"Added {result['added']}, duplicates {result['duplicate']}, no text {result['skipped_no_text']}.")
    st.rerun()

st.divider()
if not rows:
    st.info("Nothing waiting for review.")
cats = sorted(queue.categories())
for row in rows:
    with st.container(border=True):
        if row["residual"]:
            st.warning("Check before approving: " + row["residual"])
        text = st.text_area("De-identified text (edit out anything identifying)", row["text_deid"],
                            key=f"text-{row['id']}")
        left, right = st.columns(2)
        cat = left.selectbox("Category", cats, index=cats.index(row["category"]), key=f"cat-{row['id']}")
        pri = right.selectbox("Priority", queue.PRIORITIES, index=queue.PRIORITIES.index(row["priority"]),
                              key=f"pri-{row['id']}")
        approve, reject = st.columns([1, 6])
        if approve.button("Approve", key=f"ok-{row['id']}"):
            with connect() as conn:
                realset.review(conn, row["id"], True, text, cat, pri, who or "dashboard")
            st.rerun()
        if reject.button("Reject", key=f"no-{row['id']}"):
            with connect() as conn:
                realset.review(conn, row["id"], False, None, None, None, who or "dashboard")
            st.rerun()
