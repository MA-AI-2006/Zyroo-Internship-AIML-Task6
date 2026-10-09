"""DocFlow - AI Document Intelligence & Workflow Platform (Streamlit UI).

Run with:  streamlit run app.py
"""
from __future__ import annotations

import html

import altair as alt
import pandas as pd
import streamlit as st

from core import config, database, pipeline, rag, workflow
from core.errors import DocFlowError

st.set_page_config(page_title="DocFlow", page_icon="📄", layout="wide", initial_sidebar_state="expanded")
database.init_db()

PALETTE = {"approved": "#10b981", "pending_review": "#f59e0b", "rejected": "#ef4444", "failed": "#6b7280", "processing": "#6366f1"}
TYPE_ICONS = {"invoice": "🧾", "receipt": "🛒", "resume": "👤", "contract": "📜", "purchase_order": "📦", "unknown": "❓"}

CSS = """
<style>
.block-container {padding-top: 1.6rem; max-width: 1280px;}
.hero {background: linear-gradient(120deg, #4f46e5 0%, #7c3aed 55%, #db2777 100%); color: #fff;
       border-radius: 20px; padding: 26px 30px; margin-bottom: 22px; box-shadow: 0 10px 30px rgba(79,70,229,.25);}
.hero h1 {margin: 0; font-size: 1.9rem; color:#fff;} .hero p {margin: 6px 0 0; opacity: .9; font-size: 1rem;}
.kpi {background: #fff; border-radius: 16px; padding: 16px 18px; box-shadow: 0 2px 12px rgba(30,27,58,.07);
      border-top: 4px solid var(--c, #4f46e5); height: 100%;}
.kpi .v {font-size: 1.9rem; font-weight: 700; color: #1e1b3a; line-height: 1.1;}
.kpi .l {font-size: .78rem; text-transform: uppercase; letter-spacing: .06em; color: #6b6a85; margin-top: 4px;}
.badge {display:inline-block; padding: 3px 11px; border-radius: 999px; font-size: .78rem; font-weight: 600; color:#fff;}
.card {background:#fff; border-radius:16px; padding:18px 20px; box-shadow: 0 2px 12px rgba(30,27,58,.07); margin-bottom:14px;}
.bar {background:#e8e8f3; border-radius:999px; height:9px; overflow:hidden; margin-top:5px;}
.bar > div {height:100%; border-radius:999px;}
.flag {border-left: 4px solid; padding: 8px 12px; border-radius: 8px; margin: 6px 0; background:#fff; font-size:.92rem;}
.tl {border-left: 2px solid #d9d9ec; padding-left: 14px; margin-left: 6px; margin-bottom: 10px;}
.tl small {color:#6b6a85;}
section[data-testid="stSidebar"] {background: linear-gradient(180deg,#1e1b3a,#312e6b);}
section[data-testid="stSidebar"] * {color: #ecebff !important;}
section[data-testid="stSidebar"] input {color:#1e1b3a !important;}
div.stButton > button, div.stDownloadButton > button {border-radius: 10px; font-weight: 600;}
</style>
"""
st.markdown(CSS, unsafe_allow_html=True)


# ---------- helpers ----------
def badge(status: str) -> str:
    label = workflow.STATUS_LABELS.get(status, status)
    return f'<span class="badge" style="background:{PALETTE.get(status, "#6b7280")}">{html.escape(label)}</span>'


def kpi(col, value, label, color="#4f46e5"):
    col.markdown(f'<div class="kpi" style="--c:{color}"><div class="v">{value}</div><div class="l">{html.escape(label)}</div></div>', unsafe_allow_html=True)


def conf_bar(label: str, value: float | None):
    value = value or 0.0
    color = "#10b981" if value >= 0.75 else "#f59e0b" if value >= 0.5 else "#ef4444"
    st.markdown(
        f'<div style="font-size:.85rem"><b>{html.escape(label)}</b> &nbsp;{value:.0%}</div>'
        f'<div class="bar"><div style="width:{value * 100:.0f}%;background:{color}"></div></div>',
        unsafe_allow_html=True,
    )


def header(title: str, subtitle: str):
    st.markdown(f'<div class="hero"><h1>{html.escape(title)}</h1><p>{html.escape(subtitle)}</p></div>', unsafe_allow_html=True)


def docs_table(docs: list[dict]) -> pd.DataFrame:
    rows = []
    for d in docs:
        rows.append({
            "ID": d["id"], "File": d["original_name"],
            "Type": f"{TYPE_ICONS.get(d['category'] or 'unknown', '')} {(d['category'] or '-').replace('_', ' ')}",
            "Status": workflow.STATUS_LABELS.get(d["status"], d["status"]),
            "Class. conf": d["class_conf"] if d["class_conf"] is not None else None,
            "Extract conf": d["extract_conf"] if d["extract_conf"] is not None else None,
            "Issues": len(d["validation"]) + len(d["anomalies"]),
            "Time (ms)": d["processing_ms"], "Uploaded": d["uploaded_at"],
        })
    return pd.DataFrame(rows)


def show_table(docs: list[dict]):
    st.dataframe(
        docs_table(docs), use_container_width=True, hide_index=True,
        column_config={
            "Class. conf": st.column_config.ProgressColumn("Class. conf", min_value=0, max_value=1, format="%.2f"),
            "Extract conf": st.column_config.ProgressColumn("Extract conf", min_value=0, max_value=1, format="%.2f"),
        },
    )


def render_detail(doc_id: int, allow_review: bool = False):
    doc = database.get_document(doc_id)
    if not doc:
        st.error("That document no longer exists.")
        return
    icon = TYPE_ICONS.get(doc["category"] or "unknown", "📄")
    st.markdown(
        f'<div class="card"><div style="display:flex;justify-content:space-between;align-items:center;flex-wrap:wrap;gap:8px">'
        f'<div><span style="font-size:1.25rem;font-weight:700">{icon} {html.escape(doc["original_name"])}</span>'
        f'<br><small style="color:#6b6a85">#{doc["id"]} · {html.escape((doc["category"] or "unclassified").replace("_", " "))} · '
        f'{doc["pages"] or "-"} page(s) · text via {html.escape(doc["text_method"] or "-")} · uploaded {doc["uploaded_at"]} UTC</small></div>'
        f'<div>{badge(doc["status"])}</div></div></div>',
        unsafe_allow_html=True,
    )

    if doc["status"] == "failed":
        st.error(doc.get("error") or "Processing failed.")
        if doc.get("stored_name") and st.button("🔁 Retry processing", key=f"retry_{doc_id}"):
            res = pipeline.reprocess(doc_id, st.session_state.get("reviewer", "reviewer"))
            st.toast(res["message"])
            st.rerun()
        return

    if doc["analysis"]:
        st.info(f"🧠 **AI analysis** — {doc['analysis']}")

    c1, c2 = st.columns(2)
    with c1:
        conf_bar("Classification confidence", doc["class_conf"])
    with c2:
        conf_bar("Extraction confidence", doc["extract_conf"])
    st.caption(f"Workflow decision: {doc['workflow_reason']}")

    tab_f, tab_v, tab_t, tab_a, tab_p = st.tabs(["Extracted fields", "Validation & anomalies", "Text", "Audit history", "Performance"])
    with tab_f:
        fields = {k: v for k, v in doc["fields"].items() if v not in (None, "", [])}
        if fields:
            df = pd.DataFrame([{"Field": k.replace("_", " ").title(), "Value": ", ".join(v) if isinstance(v, list) else str(v)} for k, v in fields.items()])
            st.dataframe(df, use_container_width=True, hide_index=True)
        else:
            st.write("No structured fields were extracted for this document type.")
    with tab_v:
        if not doc["validation"] and not doc["anomalies"]:
            st.success("All validation checks passed and no anomalies were detected.")
        for v in doc["validation"]:
            color = "#ef4444" if v["severity"] == "error" else "#f59e0b"
            st.markdown(f'<div class="flag" style="border-color:{color}"><b>{v["severity"].title()}</b> · {html.escape(v["message"])}</div>', unsafe_allow_html=True)
        for a in doc["anomalies"]:
            st.markdown(f'<div class="flag" style="border-color:#7c3aed"><b>Anomaly</b> · {html.escape(a["message"])}</div>', unsafe_allow_html=True)
    with tab_t:
        st.text_area("Extracted text", doc["text"] or "", height=260, disabled=True, key=f"txt_{doc_id}")
    with tab_a:
        render_audit(database.get_audit(doc_id))
    with tab_p:
        t = doc["timings"] or {}
        if t:
            st.bar_chart(pd.DataFrame({"ms": {k.replace("_ms", ""): v for k, v in t.items() if k != "total_ms"}}), color="#7c3aed")
            st.caption(f"Total processing time: {t.get('total_ms', doc['processing_ms'])} ms")
        else:
            st.write("No timing data recorded.")

    if allow_review and doc["status"] == "pending_review":
        st.markdown("#### Reviewer decision")
        note = st.text_input("Note (required for rejection)", key=f"note_{doc_id}")
        b1, b2, _ = st.columns([1, 1, 4])
        for col, decision, label, kind in ((b1, "approve", "✅ Approve", "primary"), (b2, "reject", "⛔ Reject", "secondary")):
            if col.button(label, key=f"{decision}_{doc_id}", type=kind):
                try:
                    workflow.review(doc_id, decision, st.session_state.get("reviewer", "reviewer"), note)
                    st.toast(f"Document #{doc_id} {decision}d.")
                    st.rerun()
                except DocFlowError as exc:
                    st.warning(str(exc))
    elif allow_review and doc["status"] in ("approved", "rejected"):
        if st.button("↩️ Reopen for review", key=f"reopen_{doc_id}"):
            workflow.transition(doc_id, "pending_review", st.session_state.get("reviewer", "reviewer"), "Reopened")
            st.rerun()


def render_audit(events: list[dict]):
    if not events:
        st.write("No activity recorded yet.")
        return
    for e in events:
        change = f" · {e['from_status'] or '∅'} → {e['to_status']}" if e["to_status"] else ""
        name = f" · {html.escape(e['original_name'])}" if e.get("original_name") else ""
        st.markdown(
            f'<div class="tl"><b>{html.escape(e["action"].replace("_", " ").title())}</b>{change}{name}<br>'
            f'<small>{e["ts"]} UTC · {html.escape(e["actor"])}'
            f'{" · " + html.escape(e["detail"]) if e["detail"] else ""}</small></div>',
            unsafe_allow_html=True,
        )


# ---------- sidebar ----------
with st.sidebar:
    st.markdown("## 📄 DocFlow")
    st.caption("Document Intelligence & Workflow")
    page = st.radio("Navigate", ["📊 Dashboard", "⬆️ Upload", "🗂️ Documents", "🧑‍⚖️ Review Queue", "💬 Assistant", "🕒 Audit Trail"], label_visibility="collapsed")
    st.divider()
    st.session_state["reviewer"] = st.text_input("Your name (for the audit trail)", value=st.session_state.get("reviewer", "reviewer"), max_chars=40) or "reviewer"
    pending = len(database.list_documents(status="pending_review"))
    st.caption(f"{pending} document(s) waiting for review")


# ---------- pages ----------
if page.endswith("Dashboard"):
    header("Dashboard", "Live view of everything processed by the platform")
    m = database.metrics()
    cols = st.columns(6)
    kpi(cols[0], m["total"], "Documents", "#4f46e5")
    kpi(cols[1], m["by_status"].get("approved", 0), "Approved", PALETTE["approved"])
    kpi(cols[2], m["by_status"].get("pending_review", 0), "Manual review", PALETTE["pending_review"])
    kpi(cols[3], m["by_status"].get("rejected", 0), "Rejected", PALETTE["rejected"])
    kpi(cols[4], m["failed"], "Failed", PALETTE["failed"])
    kpi(cols[5], m["duplicates"], "Duplicates caught", "#7c3aed")
    st.write("")
    cols = st.columns(4)
    kpi(cols[0], m["validation_issues"], "Docs with validation issues", "#f59e0b")
    kpi(cols[1], m["anomalies"], "Docs with anomalies", "#db2777")
    kpi(cols[2], f"{m['avg_ms']} ms" if m["avg_ms"] else "–", "Avg processing time", "#0ea5e9")
    kpi(cols[3], f"{m['questions_answered']}/{m['questions']}", "Assistant questions answered", "#14b8a6")
    st.write("")

    if m["total"] == 0:
        st.info("No documents yet. Head to **Upload** to process your first document.")
    else:
        left, right = st.columns(2)
        with left:
            st.subheader("By document type")
            df = pd.DataFrame({"type": list(m["by_type"]), "count": list(m["by_type"].values())})
            st.altair_chart(alt.Chart(df).mark_bar(cornerRadiusTopLeft=6, cornerRadiusTopRight=6, color="#6366f1").encode(
                x=alt.X("type:N", title=None, sort="-y"), y=alt.Y("count:Q", title=None), tooltip=["type", "count"]).properties(height=260), use_container_width=True)
        with right:
            st.subheader("By workflow status")
            df = pd.DataFrame({"status": [workflow.STATUS_LABELS.get(s, s) for s in m["by_status"]], "count": list(m["by_status"].values()), "key": list(m["by_status"])})
            st.altair_chart(alt.Chart(df).mark_arc(innerRadius=60).encode(
                theta="count:Q", color=alt.Color("status:N", scale=alt.Scale(domain=list(df["status"]), range=[PALETTE.get(k, "#6b7280") for k in df["key"]]), legend=alt.Legend(title=None)),
                tooltip=["status", "count"]).properties(height=260), use_container_width=True)
        st.subheader("Recent workflow activity")
        render_audit(database.get_audit(limit=8))


elif page.endswith("Upload"):
    header("Upload & Process", "PDF, scanned image or text — validated, read, classified, checked and routed automatically")
    st.caption(f"Accepted: {', '.join(sorted(config.ALLOWED_EXTENSIONS))} · max {config.MAX_FILE_MB} MB per file · duplicates are detected by SHA-256 hash")
    files = st.file_uploader("Drop one or more documents", type=None, accept_multiple_files=True)
    if st.button("🚀 Process documents", type="primary", disabled=not files):
        payload = [(f.name, f.getvalue()) for f in files]
        progress = st.progress(0.0, text="Starting…")
        results = []
        for i, (name, data) in enumerate(payload, 1):
            progress.progress((i - 1) / len(payload), text=f"Processing {name} ({i}/{len(payload)})")
            results.extend(pipeline.process_batch([(name, data)], st.session_state["reviewer"]))
        progress.progress(1.0, text="Done")
        st.session_state["last_results"] = results

    results = st.session_state.get("last_results", [])
    if results:
        ok = sum(1 for r in results if r["ok"] and not r["duplicate"])
        dup = sum(1 for r in results if r["duplicate"])
        bad = sum(1 for r in results if not r["ok"])
        summary = f"Batch finished — {ok} processed, {dup} duplicate(s), {bad} failed."
        (st.success if bad == 0 else st.warning)(summary)
        for r in results:
            icon = "♻️" if r["duplicate"] else ("✅" if r["ok"] else "⚠️")
            with st.expander(f"{icon} {r.get('filename', '')} — {workflow.STATUS_LABELS.get(r['status'], r['status'])}", expanded=len(results) == 1):
                st.write(r["message"])
                if r.get("doc_id"):
                    render_detail(r["doc_id"])


elif page.endswith("Documents"):
    header("Documents", "Search, filter and inspect every stored document")
    c1, c2, c3 = st.columns([2, 1, 1])
    query = c1.text_input("Search text, filename, identifier or field", placeholder="e.g. INV-1001 or Acme")
    status = c2.selectbox("Status", ["all"] + workflow.STATES, format_func=lambda s: "All statuses" if s == "all" else workflow.STATUS_LABELS[s])
    cat = c3.selectbox("Type", ["all", "invoice", "receipt", "purchase_order", "resume", "contract", "unknown"])
    docs = database.list_documents(status, cat, query)
    st.caption(f"{len(docs)} document(s)")
    if docs:
        show_table(docs)
        pick = st.selectbox("Open a document", [d["id"] for d in docs], format_func=lambda i: next(f"#{d['id']} · {d['original_name']}" for d in docs if d["id"] == i))
        render_detail(pick, allow_review=True)
    else:
        st.info("No documents match these filters.")


elif page.endswith("Review Queue"):
    header("Review Queue", "Documents the workflow engine could not approve automatically")
    queue = database.list_documents(status="pending_review")
    if not queue:
        st.success("🎉 Nothing is waiting for review.")
    for d in reversed(queue):
        with st.expander(f"#{d['id']} · {d['original_name']} — {(d['category'] or 'unknown').replace('_', ' ')}", expanded=len(queue) == 1):
            st.caption(d["workflow_reason"])
            render_detail(d["id"], allow_review=True)


elif page.endswith("Assistant"):
    header("AI Assistant", "Ask questions answered only from your stored documents, with sources")
    if config.ANTHROPIC_API_KEY:
        st.caption("Answers are phrased by an external AI service using only retrieved excerpts. Process only documents you are allowed to share.")
    else:
        st.caption("Running fully locally (no external AI service). Add ANTHROPIC_API_KEY to .env for smoother answers.")
    if "chat" not in st.session_state:
        st.session_state["chat"] = []
    for msg in st.session_state["chat"]:
        with st.chat_message(msg["role"]):
            st.markdown(msg["content"], unsafe_allow_html=True)
    q = st.chat_input("e.g. What is the total on invoice INV-1001?")
    if q:
        st.session_state["chat"].append({"role": "user", "content": q})
        with st.chat_message("user"):
            st.markdown(q)
        with st.chat_message("assistant"):
            ans = rag.ask(q)
            text = ans.text
            if ans.answered:
                srcs = sorted({f"{h.doc_name} (#{h.doc_id})" for h in ans.hits})
                text += "\n\n**Sources:** " + ", ".join(srcs)
            st.markdown(text, unsafe_allow_html=True)
            if ans.hits:
                with st.expander("Retrieved passages"):
                    for h in ans.hits:
                        st.markdown(f"**{html.escape(h.doc_name)}** · chunk {h.chunk_idx} · similarity {h.score:.2f}")
                        st.caption(h.text)
        st.session_state["chat"].append({"role": "assistant", "content": text})
    log = database.get_question_log(20)
    if log:
        with st.expander("Assistant question log (including unanswered questions)"):
            st.dataframe(pd.DataFrame(log)[["ts", "question", "answered", "top_score"]], use_container_width=True, hide_index=True)


elif page.endswith("Audit Trail"):
    header("Audit Trail", "Every upload, decision and status change — who did what and when")
    actions = ["all", "uploaded", "processed", "status_change", "duplicate_upload", "processing_failed", "upload_rejected"]
    action = st.selectbox("Filter by action", actions)
    events = database.get_audit(limit=300, action=None if action == "all" else action)
    st.caption(f"{len(events)} event(s)")
    render_audit(events)
    if events:
        st.download_button("⬇️ Download audit log (CSV)", pd.DataFrame(events).to_csv(index=False).encode(), "audit_log.csv", "text/csv")
