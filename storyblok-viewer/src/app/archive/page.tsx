"use client";

import Link from "next/link";
import React, { useMemo, useState } from "react";
import { fmtDate, readTime, useIndex } from "../lib";
import { FACET_ORDER, HERO_ELEMENTS, type Story } from "../types";

/** Reader-facing archive: a real news listing, with the filters on top. */

function Pills({
  options,
  value,
  onChange,
  allLabel = "All",
}: {
  options: [string, number][];
  value: string;
  onChange: (v: string) => void;
  allLabel?: string;
}) {
  return (
    <div className="pillrow">
      <button className={`pill${value === "" ? " on" : ""}`} onClick={() => onChange("")}>
        {allLabel}
      </button>
      {options.map(([v, n]) => (
        <button
          key={v}
          className={`pill${value === v ? " on" : ""}`}
          onClick={() => onChange(value === v ? "" : v)}
        >
          {v} <span className="pill-n">{n}</span>
        </button>
      ))}
    </div>
  );
}

function Card({ s, feature }: { s: Story; feature?: boolean }) {
  return (
    <Link href={`/story/${s.id}`} className={`card${feature ? " feature" : ""}`}>
      <div className="card-media">
        {s.thumb ? (
          // eslint-disable-next-line @next/next/no-img-element
          <img src={s.thumb} alt="" loading="lazy" />
        ) : (
          <div className="card-noimg">no image</div>
        )}
        {s.elements.includes("video_embed") && <span className="card-play">▶</span>}
        {s.elements.includes("gif") && <span className="card-badge">GIF</span>}
        {s.elements.includes("gallery") && <span className="card-badge">GALLERY</span>}
      </div>
      <div className="card-body">
        <div className="card-meta">
          {s.region && <span className="k">{s.region}</span>}
          {s.entity && <span>{s.entity}</span>}
        </div>
        <h3 className="card-title">{s.title}</h3>
        {feature && s.excerpt && <p className="card-excerpt">{s.excerpt}</p>}
        <div className="card-foot">
          <span>{fmtDate(s.date) || "—"}</span>
          <span>·</span>
          <span>{readTime(s.counts.words, s.counts.media)}</span>
          {s.writer && (
            <>
              <span>·</span>
              <span>{s.writer}</span>
            </>
          )}
        </div>
      </div>
    </Link>
  );
}

export default function Archive() {
  const { idx, err } = useIndex();
  const [q, setQ] = useState("");
  const [region, setRegion] = useState("");
  const [entity, setEntity] = useState("");
  const [year, setYear] = useState("");
  const [writer, setWriter] = useState("");
  const [element, setElement] = useState("");
  const [sort, setSort] = useState("date-desc");
  const [limit, setLimit] = useState(24);
  const [showAdv, setShowAdv] = useState(false);

  const filtered = useMemo(() => {
    if (!idx) return [];
    const needle = q.trim().toLowerCase();
    const out = idx.stories.filter((s) => {
      if (needle) {
        const hay = `${s.title} ${s.excerpt} ${s.writer} ${s.entity} ${s.department}`.toLowerCase();
        if (!hay.includes(needle)) return false;
      }
      if (region && s.region !== region) return false;
      if (entity && s.entity !== entity) return false;
      if (year && s.year !== year) return false;
      if (writer && s.writer !== writer) return false;
      if (element && !s.elements.includes(element)) return false;
      return true;
    });
    const cmp: Record<string, (a: Story, b: Story) => number> = {
      "date-desc": (a, b) => (b.date || "").localeCompare(a.date || ""),
      "date-asc": (a, b) => (a.date || "").localeCompare(b.date || ""),
      title: (a, b) => a.title.localeCompare(b.title),
      words: (a, b) => b.counts.words - a.counts.words,
    };
    return out.sort(cmp[sort] ?? cmp["date-desc"]);
  }, [idx, q, region, entity, year, writer, element, sort]);

  const counts = useMemo(() => {
    const m = { region: new Map(), entity: new Map(), year: new Map(),
                writer: new Map(), elements: new Map() } as Record<string, Map<string, number>>;
    for (const s of filtered) {
      for (const k of ["region", "entity", "year", "writer"]) {
        const v = String((s as any)[k] ?? "");
        if (v) m[k].set(v, (m[k].get(v) ?? 0) + 1);
      }
      for (const e of s.elements) m.elements.set(e, (m.elements.get(e) ?? 0) + 1);
    }
    return m;
  }, [filtered]);

  if (err) return <div className="hollow">{err}</div>;
  if (!idx) return <div className="hollow">Loading archive…</div>;

  const top = (key: string, n: number, live: Map<string, number>) =>
    Object.keys(idx.facets[key] ?? {})
      .map((k) => [k, live.get(k) ?? 0] as [string, number])
      .sort((a, b) => b[1] - a[1] || a[0].localeCompare(b[0]))
      .slice(0, n);

  const active = [region, entity, year, writer, element].filter(Boolean).length;
  const [hero, ...rest] = filtered;

  return (
    <>
      <div className="hero-band">
        <div className="wrap">
          <h1 className="big">News archive</h1>
          <p className="lede">
            {idx.story_count.toLocaleString()} stories migrated from SharePoint,
            1999&ndash;2026. Filter by region, entity, author, year or the elements
            a story contains.
          </p>
        </div>
      </div>

      <div className="wrap">
        <div className="toolbar">
          <input
            className="bigsearch"
            placeholder="Search stories…"
            value={q}
            onChange={(e) => { setQ(e.target.value); setLimit(24); }}
          />
          <select className="sel" value={sort} onChange={(e) => setSort(e.target.value)}>
            <option value="date-desc">Newest first</option>
            <option value="date-asc">Oldest first</option>
            <option value="title">Title A–Z</option>
            <option value="words">Longest</option>
          </select>
          <button className="ghost" onClick={() => setShowAdv((v) => !v)}>
            {showAdv ? "Fewer filters" : "More filters"}
            {active > 0 && <span className="dot">{active}</span>}
          </button>
          {active > 0 && (
            <button
              className="ghost danger"
              onClick={() => { setRegion(""); setEntity(""); setYear(""); setWriter(""); setElement(""); }}
            >
              Clear
            </button>
          )}
        </div>

        <div className="filterblock">
          <div className="frow">
            <span className="flabel">Region</span>
            <Pills options={top("region", 12, counts.region)} value={region}
              onChange={(v) => { setRegion(v); setLimit(24); }} allLabel="All regions" />
          </div>
          {showAdv && (
            <>
              <div className="frow">
                <span className="flabel">Entity</span>
                <Pills options={top("entity", 20, counts.entity)} value={entity}
                  onChange={(v) => { setEntity(v); setLimit(24); }} allLabel="All entities" />
              </div>
              <div className="frow">
                <span className="flabel">Contains</span>
                <Pills
                  options={top("elements", 40, counts.elements)
                    .filter(([k]) => HERO_ELEMENTS.includes(k))
                    .map(([k, n]) => [k, n] as [string, number])}
                  value={element}
                  onChange={(v) => { setElement(v); setLimit(24); }}
                  allLabel="Anything"
                />
              </div>
              <div className="frow">
                <span className="flabel">Year</span>
                <Pills options={top("year", 32, counts.year)} value={year}
                  onChange={(v) => { setYear(v); setLimit(24); }} allLabel="All years" />
              </div>
              <div className="frow">
                <span className="flabel">Author</span>
                <Pills options={top("writer", 18, counts.writer)} value={writer}
                  onChange={(v) => { setWriter(v); setLimit(24); }} allLabel="Anyone" />
              </div>
            </>
          )}
        </div>

        <div className="resultline">
          <b>{filtered.length.toLocaleString()}</b> stor{filtered.length === 1 ? "y" : "ies"}
          {active > 0 || q ? " matching" : ""}
        </div>

        {!filtered.length && <div className="hollow">Nothing matches those filters.</div>}

        {hero && <div className="feature-slot"><Card s={hero} feature /></div>}

        <div className="cardgrid">
          {rest.slice(0, limit).map((s) => <Card key={s.id} s={s} />)}
        </div>

        {rest.length > limit && (
          <div className="loadmore">
            <button className="solid" onClick={() => setLimit((l) => l + 24)}>
              Load more · {(rest.length - limit).toLocaleString()} remaining
            </button>
          </div>
        )}
      </div>
    </>
  );
}
