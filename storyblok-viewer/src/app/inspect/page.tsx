"use client";

import React, { useCallback, useEffect, useMemo, useState } from "react";
import {
  FACET_ORDER,
  HERO_ELEMENTS,
  type Detail,
  type Index,
  type Story,
} from "../types";
import { Figure, Frame, Gallery, Label, Prose, Tweet, kindOf } from "../Media";

type Mode = "and" | "or";

const NUMERIC: { key: keyof Story["counts"]; label: string }[] = [
  { key: "words", label: "Words" },
  { key: "media", label: "Media files" },
  { key: "links", label: "Links" },
  { key: "shares", label: "Share targets" },
];

/* ------------------------------------------------------------ collapsible */

function Group({
  title,
  count,
  defaultOpen,
  right,
  children,
}: {
  title: string;
  count?: number;
  defaultOpen?: boolean;
  right?: React.ReactNode;
  children: React.ReactNode;
}) {
  const [open, setOpen] = useState(!!defaultOpen);
  return (
    <div className="group">
      <button
        className={`group-head${open ? " open" : ""}`}
        onClick={() => setOpen((o) => !o)}
      >
        <span className="caret">▶</span>
        <span className="t">{title}</span>
        {count ? <span className="badge">{count}</span> : null}
      </button>
      {open && (
        <div className="group-body">
          {right && (
            <div style={{ display: "flex", justifyContent: "flex-end", gap: 5, marginBottom: 6 }}>
              {right}
            </div>
          )}
          {children}
        </div>
      )}
    </div>
  );
}

function Options({
  options,
  chosen,
  onToggle,
  labels,
}: {
  options: [string, number][];
  chosen: Set<string>;
  onToggle: (v: string) => void;
  labels?: Record<string, string>;
}) {
  const [q, setQ] = useState("");
  const shown = q
    ? options.filter(([v]) => (labels?.[v] ?? v).toLowerCase().includes(q.toLowerCase()))
    : options;
  return (
    <>
      {options.length > 12 && (
        <input
          className="field"
          style={{ width: "100%", marginBottom: 6, fontSize: 12, padding: "5px 8px" }}
          placeholder={`filter ${options.length}…`}
          value={q}
          onChange={(e) => setQ(e.target.value)}
        />
      )}
      <div className="scroll-cap">
        {shown.map(([v, n]) => (
          <label
            className={`opt${chosen.has(v) ? " on" : ""}${n === 0 && !chosen.has(v) ? " zero" : ""}`}
            key={v}
          >
            <input type="checkbox" checked={chosen.has(v)} onChange={() => onToggle(v)} />
            <span className="lbl" title={labels?.[v] ?? v}>
              {labels?.[v] ?? v}
            </span>
            <span className="n">{n}</span>
          </label>
        ))}
        {!shown.length && <div className="hint" style={{ padding: 4 }}>no match</div>}
      </div>
    </>
  );
}

function highlight(text: string, q: string) {
  if (!q.trim()) return text;
  const parts = text.split(new RegExp(`(${q.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")})`, "ig"));
  return parts.map((p, i) =>
    p.toLowerCase() === q.toLowerCase() ? <mark key={i}>{p}</mark> : p
  );
}

/* ------------------------------------------------------------------ page */

export default function Page() {
  // /story/[id] links here with ?id=, so the inspector opens on that story
  const initial =
    typeof window !== "undefined"
      ? Number(new URLSearchParams(window.location.search).get("id")) || null
      : null;
  const [idx, setIdx] = useState<Index | null>(null);
  const [err, setErr] = useState("");
  const [collapsed, setCollapsed] = useState(false);
  const [q, setQ] = useState("");
  const [sel, setSel] = useState<number | null>(initial);
  const [detail, setDetail] = useState<Detail | null>(null);
  const [elemMode, setElemMode] = useState<Mode>("and");
  const [from, setFrom] = useState("");
  const [to, setTo] = useState("");
  const [minmax, setMinmax] = useState<Record<string, [string, string]>>({});
  const [chosen, setChosen] = useState<Record<string, Set<string>>>({});
  const [sort, setSort] = useState("date-desc");
  const [limit, setLimit] = useState(200);

  useEffect(() => {
    fetch("/data/index.json")
      .then((r) => {
        if (!r.ok) throw new Error(`index.json → HTTP ${r.status}`);
        return r.json();
      })
      .then(setIdx)
      .catch((e) => setErr(String(e)));
  }, []);

  useEffect(() => {
    if (sel == null) return setDetail(null);
    setDetail(null);
    fetch(`/data/stories/${sel}.json`)
      .then((r) => (r.ok ? r.json() : null))
      .then(setDetail)
      .catch(() => setDetail(null));
  }, [sel]);

  const toggle = useCallback((facet: string, v: string) => {
    setChosen((prev) => {
      const s = new Set(prev[facet] ?? []);
      if (s.has(v)) s.delete(v);
      else s.add(v);
      return { ...prev, [facet]: s };
    });
    setLimit(200);
  }, []);

  const filtered = useMemo(() => {
    if (!idx) return [];
    const needle = q.trim().toLowerCase();
    const els = chosen.elements ?? new Set<string>();
    const out = idx.stories.filter((s) => {
      if (needle) {
        const hay = `${s.id} ${s.seq} ${s.title} ${s.excerpt} ${s.writer} ${s.entity} ${s.department} ${s.folder}`.toLowerCase();
        if (!hay.includes(needle)) return false;
      }
      if (els.size) {
        const have = new Set(s.elements);
        const ok =
          elemMode === "and"
            ? [...els].every((e) => have.has(e))
            : [...els].some((e) => have.has(e));
        if (!ok) return false;
      }
      for (const { key } of FACET_ORDER) {
        if (key === "elements") continue;
        const c = chosen[key];
        if (c?.size && !c.has(String((s as any)[key] ?? ""))) return false;
      }
      if (from && (!s.date || s.date < from)) return false;
      if (to && (!s.date || s.date > to)) return false;
      for (const { key } of NUMERIC) {
        const [lo, hi] = minmax[key] ?? ["", ""];
        const v = s.counts[key];
        if (lo !== "" && v < Number(lo)) return false;
        if (hi !== "" && v > Number(hi)) return false;
      }
      return true;
    });
    const cmp: Record<string, (a: Story, b: Story) => number> = {
      "date-desc": (a, b) => (b.date || "").localeCompare(a.date || ""),
      "date-asc": (a, b) => (a.date || "").localeCompare(b.date || ""),
      title: (a, b) => a.title.localeCompare(b.title),
      elements: (a, b) => b.elements.length - a.elements.length,
      words: (a, b) => b.counts.words - a.counts.words,
      media: (a, b) => b.counts.media - a.counts.media,
      id: (a, b) => a.id - b.id,
    };
    return out.sort(cmp[sort] ?? cmp["date-desc"]);
  }, [idx, q, chosen, elemMode, from, to, minmax, sort]);

  /** Counts over the CURRENT result set, so facets narrow as you filter. */
  const liveCounts = useMemo(() => {
    const m: Record<string, Map<string, number>> = { elements: new Map() };
    for (const { key } of FACET_ORDER) if (key !== "elements") m[key] = new Map();
    for (const s of filtered) {
      for (const e of s.elements)
        m.elements.set(e, (m.elements.get(e) ?? 0) + 1);
      for (const { key } of FACET_ORDER) {
        if (key === "elements") continue;
        const v = String((s as any)[key] ?? "");
        if (v) m[key].set(v, (m[key].get(v) ?? 0) + 1);
      }
    }
    return m;
  }, [filtered]);

  const activeCount =
    Object.values(chosen).reduce((n, s) => n + s.size, 0) +
    (from ? 1 : 0) +
    (to ? 1 : 0) +
    Object.values(minmax).filter(([a, b]) => a || b).length;

  if (err)
    return (
      <div className="empty">
        <p><b>Could not load the index.</b></p>
        <p>{err}</p>
        <p>Generate it: <code>python scripts/migrate/build_viewer_index.py</code></p>
      </div>
    );
  if (!idx) return <div className="empty">loading…</div>;

  const opts = (key: string): [string, number][] =>
    Object.keys(idx.facets[key] ?? {})
      .map((k) => [k, liveCounts[key]?.get(k) ?? 0] as [string, number])
      .sort((a, b) => b[1] - a[1] || a[0].localeCompare(b[0]));

  return (
    <div className="shell">
      {/* ---------------------------------------------------------- sidebar */}
      <aside className={`sidebar${collapsed ? " collapsed" : ""}`}>
        <div className="sidebar-head">
          <button
            className="icobtn"
            onClick={() => setCollapsed((c) => !c)}
            title={collapsed ? "Show filters" : "Hide filters"}
          >
            {collapsed ? "»" : "«"}
          </button>
          {!collapsed && (
            <>
              <span className="brand">Filters</span>
              {activeCount > 0 && (
                <button
                  className="chipbtn warn"
                  onClick={() => {
                    setChosen({});
                    setFrom("");
                    setTo("");
                    setMinmax({});
                  }}
                >
                  clear {activeCount}
                </button>
              )}
            </>
          )}
        </div>

        {!collapsed && (
          <div className="sidebar-body">
            <Group title="Elements / components" defaultOpen
              count={chosen.elements?.size}
              right={
                <span className="seg">
                  <button className={elemMode === "and" ? "on" : ""}
                    onClick={() => setElemMode("and")} title="Must have ALL checked">
                    ALL
                  </button>
                  <button className={elemMode === "or" ? "on" : ""}
                    onClick={() => setElemMode("or")} title="Any of the checked">
                    ANY
                  </button>
                </span>
              }
            >
              <Options
                options={opts("elements")}
                chosen={chosen.elements ?? new Set()}
                onToggle={(v) => toggle("elements", v)}
                labels={idx.element_labels}
              />
            </Group>

            <Group title="Date range" count={(from ? 1 : 0) + (to ? 1 : 0)}>
              <div className="two">
                <input type="date" value={from} onChange={(e) => setFrom(e.target.value)} />
                <input type="date" value={to} onChange={(e) => setTo(e.target.value)} />
              </div>
            </Group>

            {FACET_ORDER.filter((f) => f.key !== "elements").map((f) => {
              const o = opts(f.key);
              if (!o.length) return null;
              return (
                <Group key={f.key} title={f.label} defaultOpen={f.open}
                  count={chosen[f.key]?.size}>
                  <Options
                    options={o}
                    chosen={chosen[f.key] ?? new Set()}
                    onToggle={(v) => toggle(f.key, v)}
                  />
                </Group>
              );
            })}

            <Group title="Numeric ranges"
              count={Object.values(minmax).filter(([a, b]) => a || b).length}>
              {NUMERIC.map(({ key, label }) => (
                <div key={key}>
                  <div className="sublabel">{label}</div>
                  <div className="two">
                    <input type="number" placeholder="min"
                      value={minmax[key]?.[0] ?? ""}
                      onChange={(e) =>
                        setMinmax((p) => ({ ...p, [key]: [e.target.value, p[key]?.[1] ?? ""] }))
                      } />
                    <input type="number" placeholder="max"
                      value={minmax[key]?.[1] ?? ""}
                      onChange={(e) =>
                        setMinmax((p) => ({ ...p, [key]: [p[key]?.[0] ?? "", e.target.value] }))
                      } />
                  </div>
                </div>
              ))}
            </Group>
          </div>
        )}
      </aside>

      <div className="main">
        {/* ------------------------------------------------------- list */}
        <div className="list">
          <div className="topbar">
            <input className="field" placeholder="Search title, summary, id, writer…"
              value={q} onChange={(e) => { setQ(e.target.value); setLimit(200); }} />
            <select className="field" style={{ width: 132 }} value={sort}
              onChange={(e) => setSort(e.target.value)}>
              <option value="date-desc">Newest</option>
              <option value="date-asc">Oldest</option>
              <option value="elements">Most elements</option>
              <option value="words">Longest</option>
              <option value="media">Most media</option>
              <option value="title">Title A–Z</option>
              <option value="id">ID</option>
            </select>
          </div>
          <div style={{ padding: "6px 12px", borderBottom: "1px solid var(--line-soft)" }}>
            <span className="count">
              <b>{filtered.length.toLocaleString()}</b> of {idx.story_count.toLocaleString()} stories
            </span>
          </div>

          <div className="list-scroll">
            {filtered.slice(0, limit).map((s) => (
              <button className={`row${sel === s.id ? " sel" : ""}`} key={s.id}
                onClick={() => setSel(s.id)}>
                {s.thumb ? (
                  // eslint-disable-next-line @next/next/no-img-element
                  <img className="row-thumb" src={s.thumb} alt="" loading="lazy" />
                ) : (
                  <span className="row-thumb none">no img</span>
                )}
                <span className="row-main">
                  <span className="row-title">{highlight(s.title, q)}</span>
                  <span className="row-sub">
                    <span>{s.date || "—"}</span>
                    {s.writer && <span>· {s.writer}</span>}
                    {s.status === "verified" && <span className="tag ok">in SB</span>}
                    {s.elements
                      .filter((e) => HERO_ELEMENTS.includes(e))
                      .map((e) => (
                        <span className="tag media" key={e}>
                          {idx.element_labels[e] ?? e}
                        </span>
                      ))}
                  </span>
                </span>
              </button>
            ))}
            {filtered.length > limit && (
              <div style={{ padding: 16, textAlign: "center" }}>
                <button className="btn" onClick={() => setLimit((l) => l + 400)}>
                  Load 400 more · {(filtered.length - limit).toLocaleString()} hidden
                </button>
              </div>
            )}
            {!filtered.length && <div className="empty">Nothing matches these filters.</div>}
          </div>
        </div>

        {/* ----------------------------------------------------- reader */}
        <div className="reader">
          {!sel && <div className="empty">Select a story to read it.</div>}
          {sel && !detail && <div className="empty">loading story {sel}…</div>}
          {detail && <Article d={detail} labels={idx.element_labels} />}
        </div>
      </div>
    </div>
  );
}

/* --------------------------------------------------------------- article */

function Article({ d, labels }: { d: Detail; labels: Record<string, string> }) {
  const banner = d.media.find((m) => m.role === "banner");
  const medium = d.media.filter((m) => m.role === "medium");
  const inlineImgs = d.media.filter((m) => m.role === "richtext");
  const docs = [...d.media, ...d.richtext_media].filter((m) => kindOf(m) === "doc");
  const videos = d.media.filter((m) => String(m.role ?? "").startsWith("video"));
  const gallery = inlineImgs.filter((m) => m.live_url).length >= 3 ? inlineImgs : [];

  return (
    <article className="article">
      <div className="art-kicker">
        {d.region && <span className="tag info">{d.region}</span>}
        {d.entity && <span className="tag">{d.entity}</span>}
        {d.department && <span className="tag">{d.department}</span>}
        {d.is_global && <span className="tag ok">global</span>}
        {d.status === "verified" && <span className="tag ok">in Storyblok</span>}
        {!d.media_urls_fetched && (
          <span className="tag warn">media URLs not resolved yet</span>
        )}
      </div>

      <h1>{d.title}</h1>

      <div className="art-byline">
        <span>{d.date || "no date"}</span>
        {d.writer && <span>✍ {d.writer}</span>}
        <span><code>{d.seq}</code></span>
        <span>#{d.id}</span>
        <span>{d.counts.words.toLocaleString()} words</span>
      </div>

      <div className="art-actions">
        {d.sharepoint_url && (
          <a className="btn primary" href={d.sharepoint_url} target="_blank" rel="noreferrer">
            ↗ SharePoint source
          </a>
        )}
        {d.sb_editor_url && (
          <a className="btn" href={d.sb_editor_url} target="_blank" rel="noreferrer">
            ✎ Storyblok editor
          </a>
        )}
        {d.sb_slug && (
          <a className="btn" href={`https://aku-dev.vercel.app/${d.sb_slug}`}
            target="_blank" rel="noreferrer">
            ▶ Live page
          </a>
        )}
      </div>

      {banner && <Figure m={banner} role="banner" />}
      {d.summary && <p className="art-summary">{d.summary}</p>}

      <Prose doc={d.richtext} srcToLive={d.src_to_live} />

      {gallery.length > 0 && <Gallery items={gallery} />}
      {medium.map((m, i) => <Figure key={i} m={m} role="medium" />)}
      {videos.map((m, i) => <Figure key={i} m={m} role={m.role} />)}
      {docs.map((m, i) => <Figure key={i} m={m} role="document" />)}
      {d.pull_quote?.component_type === "iframe_embed" &&
        d.page_iframes.map((u, i) => <Frame key={i} url={u} />)}

      {/* ------------------------------------------------------ inspector */}
      <div className="inspect">
        <details open>
          <summary>Elements detected ({d.elements.length})</summary>
          <div className="pad" style={{ display: "flex", gap: 5, flexWrap: "wrap" }}>
            {d.elements.map((e) => (
              <span className="tag media" key={e}>{labels[e] ?? e}</span>
            ))}
          </div>
        </details>

        <details>
          <summary>
            Media files ({d.media.length + d.richtext_media.length}) ·{" "}
            {[...d.media, ...d.richtext_media].filter((m) => m.live_url).length} resolved
          </summary>
          <div className="pad">
            <table className="grid">
              <thead>
                <tr><th></th><th>role</th><th>kind</th><th>file</th><th>caption</th></tr>
              </thead>
              <tbody>
                {[...d.media, ...d.richtext_media].map((m, i) => (
                  <tr key={i}>
                    <td>
                      {m.live_url && kindOf(m) !== "doc" && kindOf(m) !== "video" ? (
                        // eslint-disable-next-line @next/next/no-img-element
                        <img className="mini" src={m.live_url} alt="" loading="lazy" />
                      ) : (
                        <span className="hint">—</span>
                      )}
                    </td>
                    <td>{m.role ?? "—"}</td>
                    <td><span className={`mlabel ${kindOf(m)}`}>{kindOf(m)}</span></td>
                    <td>
                      {m.live_url ? (
                        <a href={m.live_url} target="_blank" rel="noreferrer">
                          <code>{m.filename ?? m.local_filename}</code>
                        </a>
                      ) : (
                        <code>{m.filename ?? m.local_filename}</code>
                      )}
                    </td>
                    <td>{m.caption ?? ""}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </details>

        <details>
          <summary>Taxonomy &amp; destination</summary>
          <div className="pad">
            <dl className="kv">
              <dt>Folder</dt><dd><code>{d.folder || "—"}</code></dd>
              <dt>Storyblok slug</dt><dd><code>{d.sb_slug || "not uploaded"}</code></dd>
              <dt>Region</dt><dd>{d.region || "—"}</dd>
              <dt>Entity</dt><dd>{d.entity || "—"}</dd>
              <dt>Department</dt><dd>{d.department || "—"}</dd>
              <dt>Placement</dt><dd>{d.placement || "—"}</dd>
              <dt>Category</dt><dd>{d.category || "—"}</dd>
              {d.shares.length > 0 && (
                <>
                  <dt>Shared to</dt>
                  <dd>{d.shares.map((s) => <div key={s}><code>{s}</code></div>)}</dd>
                </>
              )}
            </dl>
          </div>
        </details>

        {d.links.length > 0 && (
          <details>
            <summary>Links ({d.links.length})</summary>
            <div className="pad">
              <table className="grid">
                <tbody>
                  {d.links.map((l, i) => (
                    <tr key={i}>
                      <td style={{ maxWidth: 190 }}>{l.text}</td>
                      <td>
                        <a href={l.href} target="_blank" rel="noreferrer">
                          <code>{l.href.slice(0, 110)}</code>
                        </a>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </details>
        )}

        <details>
          <summary>Structure counts</summary>
          <div className="pad">
            <table className="grid">
              <tbody>
                {Object.entries({
                  ...d.node_counts,
                  ...Object.fromEntries(Object.entries(d.mark_counts).map(([k, v]) => [`mark:${k}`, v])),
                  ...Object.fromEntries(Object.entries(d.blok_counts).map(([k, v]) => [`blok:${k}`, v])),
                })
                  .sort((a, b) => b[1] - a[1])
                  .map(([k, v]) => (
                    <tr key={k}>
                      <td><code>{k}</code></td>
                      <td className="num">{v}</td>
                    </tr>
                  ))}
              </tbody>
            </table>
          </div>
        </details>

        {d.unmatched_page_images.length > 0 && (
          <details>
            <summary>
              Images on the SharePoint page not matched to an export record (
              {d.unmatched_page_images.length})
            </summary>
            <div className="pad gallery-grid">
              {d.unmatched_page_images.map((u) => (
                // eslint-disable-next-line @next/next/no-img-element
                <img key={u} src={u} alt="" loading="lazy" />
              ))}
            </div>
          </details>
        )}
      </div>
    </article>
  );
}
