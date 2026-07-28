"use client";

import Link from "next/link";
import React, { useMemo, useState } from "react";
import { useFolders, useIndex, type FolderNode } from "../lib";

/**
 * Folder structure as a branching tree.
 *
 * Left-to-right, with drawn elbow connectors between a parent and its children,
 * so it reads like a file tree / org chart. Click a node to open or close that
 * branch. Nothing is 3D — the branches are the point.
 */

const LEVEL: Record<string, { color: string; icon: string; label: string }> = {
  root: { color: "var(--fg)", icon: "◈", label: "Root" },
  region: { color: "var(--accent)", icon: "◉", label: "Region" },
  "entities-root": { color: "var(--faint)", icon: "▤", label: "Entities" },
  entity: { color: "var(--violet)", icon: "▣", label: "Entity" },
  "departments-root": { color: "var(--faint)", icon: "▤", label: "Departments" },
  department: { color: "var(--green)", icon: "◧", label: "Department" },
  news: { color: "var(--amber)", icon: "▸", label: "News" },
};

function deepCount(n: FolderNode): number {
  return (n.story_count ?? 0) + (n.children ?? []).reduce((s, c) => s + deepCount(c), 0);
}

function matches(n: FolderNode, q: string): boolean {
  if (!q) return true;
  const s = q.toLowerCase();
  return (
    n.name.toLowerCase().includes(s) ||
    (n.children ?? []).some((c) => matches(c, s))
  );
}

function Branch({
  n,
  q,
  openSet,
  toggle,
  onPick,
  picked,
  isLast,
}: {
  n: FolderNode;
  q: string;
  openSet: Set<string>;
  toggle: (slug: string) => void;
  onPick: (n: FolderNode) => void;
  picked: string | null;
  isLast: boolean;
}) {
  if (!matches(n, q)) return null;

  const kids = (n.children ?? []).filter((c) => matches(c, q));
  const hasKids = kids.length > 0;
  // searching opens the path to every hit; otherwise honour the click state
  const open = q ? true : openSet.has(n.full_slug);
  const meta = LEVEL[n.level] ?? { color: "var(--dim)", icon: "•", label: n.level };
  const total = deepCount(n);
  const isNews = n.level === "news";

  return (
    <li className={`br${isLast ? " last" : ""}`}>
      <div className="br-line">
        <button
          className={`br-knob${hasKids ? "" : " leaf"}${open ? " open" : ""}`}
          onClick={() => hasKids && toggle(n.full_slug)}
          aria-label={hasKids ? (open ? "Collapse" : "Expand") : undefined}
          style={{ ["--c" as any]: meta.color }}
        >
          {hasKids ? (open ? "−" : "+") : "•"}
        </button>

        <button
          className={`br-node lv-${n.level}${picked === n.full_slug ? " picked" : ""}`}
          style={{ ["--c" as any]: meta.color }}
          onClick={() => {
            onPick(n);
            if (hasKids) toggle(n.full_slug);
          }}
        >
          <span className="br-ico">{meta.icon}</span>
          <span className="br-name">
            {q
              ? n.name
                  .split(new RegExp(`(${q.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")})`, "ig"))
                  .map((p, i) =>
                    p.toLowerCase() === q.toLowerCase() ? <mark key={i}>{p}</mark> : p
                  )
              : n.name}
          </span>
          {n.entity_short && <span className="br-short">{n.entity_short}</span>}
          {total > 0 && (
            <span className={`br-n${isNews ? " live" : ""}`}>
              {total.toLocaleString()}
            </span>
          )}
          {hasKids && !open && <span className="br-more">{kids.length}</span>}
        </button>
      </div>

      {hasKids && open && (
        <ul className="br-kids">
          {kids.map((c, i) => (
            <Branch
              key={c.full_slug}
              n={c}
              q={q}
              openSet={openSet}
              toggle={toggle}
              onPick={onPick}
              picked={picked}
              isLast={i === kids.length - 1}
            />
          ))}
        </ul>
      )}
    </li>
  );
}

export default function TreePage() {
  const { doc, err } = useFolders();
  const { idx } = useIndex();
  const [q, setQ] = useState("");
  const [picked, setPicked] = useState<FolderNode | null>(null);
  const [openSet, setOpenSet] = useState<Set<string>>(
    () => new Set(["global", "regions"])
  );

  const toggle = (slug: string) =>
    setOpenSet((prev) => {
      const s = new Set(prev);
      if (s.has(slug)) s.delete(slug);
      else s.add(slug);
      return s;
    });

  const allSlugs = useMemo(
    () => (doc ? doc.folders.map((f) => f.full_slug) : []),
    [doc]
  );

  const stats = useMemo(() => {
    if (!doc) return null;
    const by: Record<string, number> = {};
    for (const f of doc.folders) by[f.level] = (by[f.level] ?? 0) + 1;
    return by;
  }, [doc]);

  if (err)
    return (
      <div className="hollow">
        <p>{err}</p>
        <p className="hint">
          Generate it: <code>python scripts/migrate/build_folders_only.py</code>
        </p>
      </div>
    );
  if (!doc) return <div className="hollow">Loading structure…</div>;

  return (
    <>
      <div className="hero-band">
        <div className="wrap">
          <h1 className="big">Folder structure</h1>
          <p className="lede">
            {doc.folders.length} folders holding{" "}
            {idx?.story_count.toLocaleString() ?? "3,606"} stories. Click a branch
            to open it.
          </p>
          {stats && (
            <div className="statrow">
              {(["region", "entity", "department", "news"] as const).map((k) => (
                <div className="stat" key={k}>
                  <b style={{ color: LEVEL[k].color }}>{stats[k] ?? 0}</b>
                  <span>{LEVEL[k].label.toLowerCase()} folders</span>
                </div>
              ))}
            </div>
          )}
        </div>
      </div>

      <div className="wrap">
        <div className="toolbar">
          <input
            className="bigsearch"
            placeholder="Find a region, entity or department…"
            value={q}
            onChange={(e) => setQ(e.target.value)}
          />
          <button className="ghost" onClick={() => setOpenSet(new Set(allSlugs))}>
            Expand all
          </button>
          <button
            className="ghost"
            onClick={() => setOpenSet(new Set(["global", "regions"]))}
          >
            Collapse all
          </button>
        </div>

        <div className="legend">
          {(["region", "entity", "department", "news"] as const).map((k) => (
            <span key={k}>
              <span style={{ color: LEVEL[k].color }}>{LEVEL[k].icon}</span>{" "}
              {LEVEL[k].label}
            </span>
          ))}
        </div>

        <div className="treewrap">
          <ul className="br-root">
            {doc.tree.map((n, i) => (
              <Branch
                key={n.full_slug}
                n={n}
                q={q}
                openSet={openSet}
                toggle={toggle}
                onPick={setPicked}
                picked={picked?.full_slug ?? null}
                isLast={i === doc.tree.length - 1}
              />
            ))}
          </ul>
        </div>

        {picked && (
          <div className="l3-panel">
            <button className="l3-close" onClick={() => setPicked(null)}>
              ×
            </button>
            <span className="rv-label">
              {(LEVEL[picked.level] ?? { label: picked.level }).label}
            </span>
            <h3>{picked.name}</h3>
            <dl className="kv">
              <dt>Path</dt>
              <dd><code>{picked.display_path}</code></dd>
              <dt>Slug</dt>
              <dd><code>{picked.full_slug}</code></dd>
              {picked.region && (<><dt>Region</dt><dd>{picked.region}</dd></>)}
              {picked.entity && (<><dt>Entity</dt><dd>{picked.entity}</dd></>)}
              {picked.department && (
                <><dt>Department</dt><dd>{picked.department}</dd></>
              )}
              <dt>Stories here</dt>
              <dd>{(picked.story_count ?? 0).toLocaleString()}</dd>
              <dt>Including children</dt>
              <dd>{deepCount(picked).toLocaleString()}</dd>
            </dl>
            {(picked.story_count ?? 0) > 0 && (
              <Link className="btn primary" href="/archive">
                Browse these in the archive →
              </Link>
            )}
          </div>
        )}
      </div>
    </>
  );
}
