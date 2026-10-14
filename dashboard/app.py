"""Triage queue. Run locally with:  .venv/bin/streamlit run dashboard/app.py --server.address localhost

Messages sorted by priority, then deadline, overdue in red. Mark replied closes a sender's open items and
resets their repeat-message count. Correct label records the right category and priority for review.
There is no login: run it on your own machine only, never on a public URL.
"""
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import streamlit as st  # noqa: E402

from app import queue  # noqa: E402
from app.store import connect  # noqa: E402
from triage.config import load_dotenv  # noqa: E402

load_dotenv()
COLORS = {"P0": "red", "P1": "orange", "P2": "blue", "P3": "gray"}
REFRESH_SECONDS = 20

st.set_page_config(page_title="Gifter triage queue", layout="wide")
st.title("Gifter triage queue")

with st.sidebar:
    st.header("Filters")
    who = st.text_input("Your name (saved with replies and corrections)", value="")
    shown = st.multiselect("Priorities", queue.PRIORITIES, default=queue.PRIORITIES)
    show_replied = st.checkbox("Show replied items", value=False)
    category_filter = st.multiselect("Categories", sorted(queue.categories()), default=[])
    st.caption(f"Refreshes every {REFRESH_SECONDS} seconds. Overdue items are red.")


def refresh() -> None:
    """Re-run just the queue when possible, else the whole page."""
    try:
        st.rerun(scope="fragment")
    except st.errors.StreamlitAPIException:
        st.rerun()


def meta_line(item: dict) -> str:
    when = datetime.fromisoformat(item["received_at"]).strftime("%b %d %H:%M UTC")
    tail = (item["wa_from"] or "")[-4:]
    parts = [item["profile_name"] or "unknown sender", f"...{tail}", when]
    if item["mentions_host"]:
        parts.append(f"host: {item['mentions_host']}")
    return " · ".join(parts)


def timing(item: dict) -> str:
    if item["replied"]:
        return ":green[replied]"
    if item["overdue"]:
        return f":red[**OVERDUE by {-item['minutes_left']} min**]"
    return f"due in {item['minutes_left']} min"


def render_item(item: dict) -> None:
    color = COLORS[item["priority"]]
    category = item["category"] or "needs a human look"
    with st.container(border=True):
        top = f":{color}[**{item['priority']}**] **{category}** · {timing(item)}"
        flags = [f for f, on in (("SAFETY", item["safety_flag"]), ("SECURITY", item["security_flag"])) if on]
        if flags:
            top += " · :red[**" + " + ".join(flags) + " FLAG**]"
        if item["fallback"]:
            top += f" · :orange[{item['fallback']}]"
        if item["churn_signal"]:
            top += " · :orange[churn signal]"
        if item["corrected_category"]:
            top += f" · :green[corrected: {item['corrected_category']} {item['corrected_priority']}]"
        st.markdown(top)
        st.caption(meta_line(item))
        if item["summary"]:
            st.write(item["summary"])
        st.markdown(f"> {item['text_display']}")
        left, right = st.columns([1, 3])
        if not item["replied"] and left.button("Mark replied", key=f"reply-{item['result_id']}"):
            with connect() as conn:
                queue.mark_replied(conn, item["wa_from"], who or "dashboard")
            refresh()
        with right.expander("Correct label"):
            cats = sorted(queue.categories())
            current = item["corrected_category"] or item["category"]
            cat = st.selectbox("Right category", cats, key=f"cat-{item['result_id']}",
                               index=cats.index(current) if current in cats else 0)
            pri = st.selectbox("Right priority", queue.PRIORITIES, key=f"pri-{item['result_id']}",
                               index=queue.PRIORITIES.index(item["corrected_priority"] or item["priority"]))
            note = st.text_input("Note (optional)", key=f"note-{item['result_id']}")
            if st.button("Save correction", key=f"save-{item['result_id']}"):
                with connect() as conn:
                    queue.save_correction(conn, item["message_id"], cat, pri, note, who or "dashboard")
                st.success("Saved.")


@st.fragment(run_every=REFRESH_SECONDS)
def show_queue() -> None:
    try:
        with connect() as conn:
            items = queue.fetch_queue(conn, include_replied=show_replied)
    except Exception as exc:  # missing tables, bad DATABASE_URL, database down
        st.error(f"Could not load the queue: {type(exc).__name__}. Check DATABASE_URL and that "
                 "sql/phase3.sql and sql/phase4.sql have been run.")
        return
    counts = queue.stats(items)
    cols = st.columns(6)
    cols[0].metric("Open", counts["open"])
    for col, p in zip(cols[1:5], queue.PRIORITIES):
        col.metric(p, counts[p])
    cols[5].metric("Overdue", counts["overdue"])
    visible = [i for i in items if i["priority"] in shown
               and (not category_filter or i["category"] in category_filter)]
    if not visible:
        st.info("Nothing in the queue for these filters.")
    for item in visible:
        render_item(item)


show_queue()
