"use client";

import Link from "next/link";
import React, { useMemo, useState } from "react";
import { useFolders, useIndex, type FolderNode } from "../lib";

/** The Storyblok folder structure, as a browsable tree. */

const ICON: Record<string, string> = {
  root: "◈",
  region: "◉",
  "entities-root": "▤",
  entity: "▣",
  "departments-root": "▤",
  department: "◧",
  news: "▸",
};

function countDeep(n: FolderNode): number {
  return (
    (n.story_count ?? 0) +
    (n.children ?? []).reduce((s, c) => s + countDeep(c), 0)
  );
}

function Node({
  n,
  depth,
  openAll,
  q,
}: {
  n: FolderNode;
  depth: number;
  openAll: boolean;
  q: string;
}) {
  const matches = (node: FolderNode): boolean => {
    if (!q) return true;
    const hit = node.name.toLowerCase().includes(q.toLowerCase());
    return hit || (node.children ?? []).some(matches);
  };
  const [open, setOpen] = useState(depth < 2);
  const show = openAll || open || (!!q && depth < 4);
  if (!matches(n)) return null;

  const kids = n.children ?? [];
  const deep = countDeep(n);
  const isNews = n.level === "news";

  return (
    <div className="tnode" style={{ ["--d" as any]: depth }}>
      <div className={`trow lvl-${n.level}`}>
        {kids.length > 0 ? (
          <button className="tcaret" onClick={() => setOpen((o) => !o)}>
            {show ? "▾" : "▸"}
          </button>
        ) : (
          <span className="tcaret dot">·</span>
        )}
        <span className={`tico ${n.level}`}>{ICON[n.level] ?? "•"}</span>
        <span className="tname">
          {q
            ? n.name
                .split(new RegExp(`(${q.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")})`, "ig"))
                .map((p, i) =>
                  p.toLowerCase() === q.toLowerCase() ? <mark key={i}>{p}</mark> : p
                )
            : n.name}
          {n.entity_short && n.level === "entity" && (
            <span className="tshort">{n.entity_short}</span>
          )}
        </span>
        {isNews && (n.story_count ?? 0) > 0 && (
          <Link className="tcount live" href={`/archive?folder=${encodeURIComponent(n.display_path)}`}>
            {n.story_count} stories
          </Link>
        )}
        {!isNews && deep > 0 && <span className="tcount">{deep}</span>}
        <code className="tslug">{n.full_slug}</code>
      </div>
      {show && kids.length > 0 && (
        <div className="tkids">
          {kids.map((c) => (
            <Node key={c.full_slug} n={c} depth={depth + 1} openAll={openAll} q={q} />
          ))}
        </div>
      )}
    </div>
  );
}

export default function TreePage() {
  const { doc, err } = useFolders();
  const { idx } = useIndex();
  const [q, setQ] = useState("");
  const [openAll, setOpenAll] = useState(false);

  const stats = useMemo(() => {
    if (!doc) return null;
    const byLevel: Record<string, number> = {};
    for (const f of doc.folders) byLevel[f.level] = (byLevel[f.level] ?? 0) + 1;
    return byLevel;
  }, [doc]);

  if (err)
    return (
      <div className="hollow">
        <p>{err}</p>
        <p className="hint">
          Generate it: <code>python scripts/migrate/build_folders_only.py</code> then{" "}
          <code>build_viewer_index.py</code>
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
            How the {idx?.story_count.toLocaleString() ?? "3,606"} stories will sit
            in Storyblok. <b>{doc.folders.length}</b> folders — regions hold
            entities, entities hold departments, and every level has its own News
            folder.
          </p>
          {stats && (
            <div className="statrow">
              {[
                ["region", "regions"],
                ["entity", "entity folders"],
                ["department", "department folders"],
                ["news", "news folders"],
              ].map(([k, label]) => (
                <div className="stat" key={k}>
                  <b>{stats[k] ?? 0}</b>
                  <span>{label}</span>
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
          <button className="ghost" onClick={() => setOpenAll((o) => !o)}>
            {openAll ? "Collapse all" : "Expand all"}
          </button>
        </div>

        <div className="legend">
          {[
            ["region", "Region"],
            ["entity", "Entity"],
            ["department", "Department"],
            ["news", "News folder"],
          ].map(([k, label]) => (
            <span key={k}>
              <span className={`tico ${k}`}>{ICON[k]}</span> {label}
            </span>
          ))}
        </div>

        <div className="treebox">
          {doc.tree.map((n) => (
            <Node key={n.full_slug} n={n} depth={0} openAll={openAll} q={q} />
          ))}
        </div>
      </div>
    </>
  );
}
