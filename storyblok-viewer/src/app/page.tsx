"use client";

import React, { useEffect, useMemo, useState, useCallback } from "react";
import { FACET_ORDER, type Detail, type Index, type Story } from "./types";
import { MediaList, RichText } from "./RichText";

/** AND = story must have every checked element; OR = any of them. */
type Mode = "and" | "or";

const NUMERIC: { key: keyof Story["counts"]; label: string }[] = [
  { key: "words", label: "Words" },
  { key: "media", label: "Media files" },
  { key: "links", label: "Links" },
  { key: "shares", label: "Share targets" },
];

function Facet({
  title,
  options,
  chosen,
  onToggle,
  onClear,
  labels,
  mode,
  onMode,
}: {
  title: string;
  options: [string, number][];
  chosen: Set<string>;
  onToggle: (v: string) => void;
  onClear: () => void;
  labels?: Record<string, string>;
  mode?: Mode;
  onMode?: (m: Mode) => void;
}) {
  const [q, setQ] = useState("");
  const shown = q
    ? options.filter(([v]) =>
        (labels?.[v] ?? v).toLowerCase().includes(q.toLowerCase())
      )
    : options;
  return (
    <div className="facet">
      <h3>
        <span>{title}</span>
        <span style={{ display: "flex", gap: 4, alignItems: "center" }}>
          {onMode && (
            <span className="mode">
              <button
                className={mode === "and" ? "on" : ""}
                onClick={() => onMode("and")}
                title="Story must contain ALL checked elements"
              >
                ALL
              </button>
              <button
                className={mode === "or" ? "on" : ""}
                onClick={() => onMode("or")}
                title="Story may contain ANY checked element"
              >
                ANY
              </button>
            </span>
          )}
          {chosen.size > 0 && (
            <button className="mini" onClick={onClear}>
              clear
            </button>
          )}
        </span>
      </h3>
      {options.length > 12 && (
        <input
          className="search"
          style={{ marginBottom: 6, fontSize: 12, padding: "4px 7px" }}
          placeholder={`filter ${options.length}…`}
          value={q}
          onChange={(e) => setQ(e.target.value)}
        />
      )}
      <div className="facet-scroll">
        {shown.map(([v, n]) => (
          <label className={`opt${chosen.has(v) ? " on" : ""}`} key={v}>
            <input
              type="checkbox"
              checked={chosen.has(v)}
              onChange={() => onToggle(v)}
            />
            <span className="lbl" title={labels?.[v] ?? v}>
              {labels?.[v] ?? v}
            </span>
            <span className="n">{n}</span>
          </label>
        ))}
        {!shown.length && (
          <div style={{ fontSize: 12, color: "var(--fg-faint)" }}>no match</div>
        )}
      </div>
    </div>
  );
}

function highlight(text: string, q: string) {
  if (!q.trim()) return text;
  const parts = text.split(
    new RegExp(`(${q.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")})`, "ig")
  );
  return parts.map((p, i) =>
    p.toLowerCase() === q.toLowerCase() ? <mark key={i}>{p}</mark> : p
  );
}

export default function Page() {
  const [idx, setIdx] = useState<Index | null>(null);
  const [err, setErr] = useState("");
  const [q, setQ] = useState("");
  const [sel, setSel] = useState<number | null>(null);
  const [detail, setDetail] = useState<Detail | null>(null);
  const [elemMode, setElemMode] = useState<Mode>("and");
  const [from, setFrom] = useState("");
  const [to, setTo] = useState("");
  const [minmax, setMinmax] = useState<Record<string, [string, string]>>({});
  const [chosen, setChosen] = useState<Record<string, Set<string>>>({});
  const [sort, setSort] = useState("date-desc");
  const [limit, setLimit] = useState(300);

  useEffect(() => {
    fetch("./data/index.json")
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
    fetch(`./data/stories/${sel}.json`)
      .then((r) => (r.ok ? r.json() : null))
      .then(setDetail)
      .catch(() => setDetail(null));
  }, [sel]);

  const toggle = useCallback((facet: string, v: string) => {
    setChosen((prev) => {
      const s = new Set(prev[facet] ?? []);
      s.has(v) ? s.delete(v) : s.add(v);
      return { ...prev, [facet]: s };
    });
  }, []);

  const filtered = useMemo(() => {
    if (!idx) return [];
    const needle = q.trim().toLowerCase();
    const els = chosen.elements ?? new Set<string>();

    let out = idx.stories.filter((s) => {
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
        const c = chosen[key as string];
        if (c?.size && !c.has(String(s[key as keyof Story] ?? ""))) return false;
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
      "title": (a, b) => a.title.localeCompare(b.title),
      "elements": (a, b) => b.elements.length - a.elements.length,
      "words": (a, b) => b.counts.words - a.counts.words,
      "media": (a, b) => b.counts.media - a.counts.media,
      "id": (a, b) => a.id - b.id,
    };
    return out.sort(cmp[sort] ?? cmp["date-desc"]);
  }, [idx, q, chosen, elemMode, from, to, minmax, sort]);

  /** Element counts recomputed over the current result set, not the whole corpus. */
  const liveElementCounts = useMemo(() => {
    const c = new Map<string, number>();
    for (const s of filtered) for (const e of s.elements) c.set(e, (c.get(e) ?? 0) + 1);
    return c;
  }, [filtered]);

  if (err)
    return (
      <div className="empty">
        <p>
          <b>Could not load the index.</b>
        </p>
        <p>{err}</p>
        <p>
          Generate it first:
          <br />
          <code>python scripts/migrate/build_viewer_index.py</code>
        </p>
      </div>
    );
  if (!idx) return <div className="empty">loading 3606 stories…</div>;

  const activeCount =
    Object.values(chosen).reduce((n, s) => n + s.size, 0) +
    (from ? 1 : 0) +
    (to ? 1 : 0) +
    Object.values(minmax).filter(([a, b]) => a || b).length;

  return (
    <div className="shell">
      <aside className="sidebar">
        <div style={{ display: "flex", justifyContent: "space-between", marginBottom: 12 }}>
          <strong style={{ fontSize: 13 }}>Filters</strong>
          {activeCount > 0 && (
            <button
              className="mini"
              onClick={() => {
                setChosen({});
                setFrom("");
                setTo("");
                setMinmax({});
              }}
            >
              reset {activeCount}
            </button>
          )}
        </div>

        <div className="facet">
          <h3>Date range</h3>
          <div className="range">
            <input type="date" value={from} onChange={(e) => setFrom(e.target.value)} />
            <input type="date" value={to} onChange={(e) => setTo(e.target.value)} />
          </div>
        </div>

        <Facet
          title={`Elements / components`}
          options={Object.entries(idx.facets.elements ?? {})
            .map(([k]) => [k, liveElementCounts.get(k) ?? 0] as [string, number])
            .sort((a, b) => b[1] - a[1])}
          chosen={chosen.elements ?? new Set()}
          onToggle={(v) => toggle("elements", v)}
          onClear={() => setChosen((p) => ({ ...p, elements: new Set() }))}
          labels={idx.element_labels}
          mode={elemMode}
          onMode={setElemMode}
        />

        {FACET_ORDER.filter((f) => f.key !== "elements").map((f) => {
          const opts = Object.entries(idx.facets[f.key as string] ?? {});
          if (!opts.length) return null;
          return (
            <Facet
              key={f.key as string}
              title={f.label}
              options={opts as [string, number][]}
              chosen={chosen[f.key as string] ?? new Set()}
              onToggle={(v) => toggle(f.key as string, v)}
              onClear={() =>
                setChosen((p) => ({ ...p, [f.key as string]: new Set() }))
              }
            />
          );
        })}

        <div className="facet">
          <h3>Numeric ranges</h3>
          {NUMERIC.map(({ key, label }) => (
            <div key={key} style={{ marginBottom: 6 }}>
              <div style={{ fontSize: 12, color: "var(--fg-dim)" }}>{label}</div>
              <div className="range">
                <input
                  type="number"
                  placeholder="min"
                  value={minmax[key]?.[0] ?? ""}
                  onChange={(e) =>
                    setMinmax((p) => ({
                      ...p,
                      [key]: [e.target.value, p[key]?.[1] ?? ""],
                    }))
                  }
                />
                <input
                  type="number"
                  placeholder="max"
                  value={minmax[key]?.[1] ?? ""}
                  onChange={(e) =>
                    setMinmax((p) => ({
                      ...p,
                      [key]: [p[key]?.[0] ?? "", e.target.value],
                    }))
                  }
                />
              </div>
            </div>
          ))}
        </div>
      </aside>

      <div className="main">
        <div className="list">
          <div className="topbar">
            <input
              className="search"
              placeholder="Search title, summary, id, sequence, writer, folder…"
              value={q}
              onChange={(e) => setQ(e.target.value)}
            />
            <select
              className="search"
              style={{ flex: "none", width: 150 }}
              value={sort}
              onChange={(e) => setSort(e.target.value)}
            >
              <option value="date-desc">Newest first</option>
              <option value="date-asc">Oldest first</option>
              <option value="elements">Most elements</option>
              <option value="words">Longest</option>
              <option value="media">Most media</option>
              <option value="title">Title A–Z</option>
              <option value="id">SharePoint id</option>
            </select>
            <span className="count">
              {filtered.length.toLocaleString()} / {idx.story_count.toLocaleString()}
            </span>
          </div>

          {filtered.slice(0, limit).map((s) => (
            <button
              className={`row${sel === s.id ? " sel" : ""}`}
              key={s.id}
              onClick={() => setSel(s.id)}
            >
              <div className="row-top">
                <span className="row-id">{s.id}</span>
                <span className="row-title">{highlight(s.title, q)}</span>
                <span className="row-date">{s.date || "—"}</span>
              </div>
              <div className="row-meta">
                {s.status === "verified" && <span className="chip good">in SB</span>}
                {s.region && <span className="chip">{s.region}</span>}
                {s.entity && <span className="chip">{s.entity}</span>}
                {s.department && <span className="chip">{s.department}</span>}
                {s.writer && <span className="chip">✍ {s.writer}</span>}
                {s.elements
                  .filter((e) =>
                    [
                      "video_embed", "video_file", "twitter_embed", "iframe_embed",
                      "gallery", "gif", "table", "pdf", "doc", "inline_image",
                      "urdu", "thumbnail", "no_media",
                    ].includes(e)
                  )
                  .map((e) => (
                    <span className="chip el" key={e}>
                      {idx.element_labels[e] ?? e}
                    </span>
                  ))}
                <span className="chip">{s.counts.words}w</span>
              </div>
            </button>
          ))}

          {filtered.length > limit && (
            <div style={{ padding: 14, textAlign: "center" }}>
              <button className="btn" onClick={() => setLimit((l) => l + 500)}>
                show 500 more ({(filtered.length - limit).toLocaleString()} hidden)
              </button>
            </div>
          )}
          {!filtered.length && <div className="empty">nothing matches these filters</div>}
        </div>

        <div className="detail">
          {!sel && <div className="empty">Pick a story to inspect it.</div>}
          {sel && !detail && <div className="empty">loading story {sel}…</div>}
          {detail && (
            <>
              <h2>{detail.title}</h2>
              <div style={{ color: "var(--fg-dim)", fontSize: 13, marginBottom: 8 }}>
                {detail.date || "no date"} · {detail.writer || "no writer"} ·{" "}
                <code>{detail.seq}</code>
              </div>

              <div className="links">
                {detail.sharepoint_url && (
                  <a className="btn" href={detail.sharepoint_url} target="_blank" rel="noreferrer">
                    ↗ SharePoint (live)
                  </a>
                )}
                {detail.sb_editor_url && (
                  <a className="btn" href={detail.sb_editor_url} target="_blank" rel="noreferrer">
                    ✎ Storyblok editor
                  </a>
                )}
                {detail.sb_slug && (
                  <a
                    className="btn"
                    href={`https://aku-dev.vercel.app/${detail.sb_slug}`}
                    target="_blank"
                    rel="noreferrer"
                  >
                    ▶ Storyblok (live)
                  </a>
                )}
              </div>

              <h4>Taxonomy</h4>
              <dl className="kv">
                <dt>Folder</dt>
                <dd><code>{detail.folder || "—"}</code></dd>
                <dt>Region</dt>
                <dd>{detail.region || "—"}</dd>
                <dt>Entity</dt>
                <dd>{detail.entity || "—"}</dd>
                <dt>Department</dt>
                <dd>{detail.department || "—"}</dd>
                <dt>Placement</dt>
                <dd>{detail.placement || "—"}</dd>
                <dt>Global flag</dt>
                <dd>{detail.is_global ? "yes" : "no"}</dd>
                {detail.shares.length > 0 && (
                  <>
                    <dt>Shared to</dt>
                    <dd>
                      {detail.shares.map((s) => (
                        <div key={s}><code>{s}</code></div>
                      ))}
                    </dd>
                  </>
                )}
              </dl>

              <h4>Elements present ({detail.elements.length})</h4>
              <div style={{ display: "flex", gap: 5, flexWrap: "wrap" }}>
                {detail.elements.map((e) => (
                  <span className="chip el" key={e}>
                    {(detail as any).element_label?.[e] ?? e}
                  </span>
                ))}
              </div>

              <h4>Media ({detail.media.length + detail.richtext_media.length})</h4>
              <MediaList items={[...detail.media, ...detail.richtext_media]} />

              {detail.links.length > 0 && (
                <>
                  <h4>Links ({detail.links.length})</h4>
                  <table className="grid">
                    <tbody>
                      {detail.links.slice(0, 40).map((l, i) => (
                        <tr key={i}>
                          <td style={{ maxWidth: 150 }}>{l.text}</td>
                          <td>
                            <a href={l.href} target="_blank" rel="noreferrer">
                              <code>{l.href.slice(0, 90)}</code>
                            </a>
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </>
              )}

              <h4>Structure</h4>
              <table className="grid">
                <tbody>
                  {Object.entries({
                    ...detail.node_counts,
                    ...Object.fromEntries(
                      Object.entries(detail.mark_counts).map(([k, v]) => [
                        `mark:${k}`,
                        v,
                      ])
                    ),
                    ...Object.fromEntries(
                      Object.entries(detail.blok_counts).map(([k, v]) => [
                        `blok:${k}`,
                        v,
                      ])
                    ),
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

              <h4>Summary</h4>
              <p style={{ fontSize: 13 }}>{detail.summary || "—"}</p>

              <h4>Body</h4>
              <RichText doc={detail.richtext} />
            </>
          )}
        </div>
      </div>
    </div>
  );
}
