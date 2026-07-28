"use client";

import Link from "next/link";
import React, { useMemo, useRef, useState } from "react";
import { useFolders, useIndex, type FolderNode } from "../lib";

/**
 * The folder structure in 3D.
 *
 * Each depth sits on its own Z plane, so the hierarchy reads as physical layers
 * rather than indentation. Drag to orbit, scroll to zoom. CSS 3D transforms
 * only — no WebGL, so it stays light and works without a canvas.
 */

const LEVEL_COLOR: Record<string, string> = {
  root: "var(--fg)",
  region: "var(--accent)",
  "entities-root": "var(--faint)",
  entity: "var(--violet)",
  "departments-root": "var(--faint)",
  department: "var(--green)",
  news: "var(--amber)",
};

const ICON: Record<string, string> = {
  root: "◈", region: "◉", "entities-root": "▤", entity: "▣",
  "departments-root": "▤", department: "◧", news: "▸",
};

function deepCount(n: FolderNode): number {
  return (n.story_count ?? 0) + (n.children ?? []).reduce((s, c) => s + deepCount(c), 0);
}

/** One card, positioned on its own Z plane. */
function Card3D({
  n,
  depth,
  q,
  onPick,
  picked,
}: {
  n: FolderNode;
  depth: number;
  q: string;
  onPick: (n: FolderNode) => void;
  picked: string | null;
}) {
  const [open, setOpen] = useState(depth < 1);
  const kids = n.children ?? [];
  const total = deepCount(n);

  const hit = (node: FolderNode): boolean => {
    if (!q) return true;
    return (
      node.name.toLowerCase().includes(q.toLowerCase()) ||
      (node.children ?? []).some(hit)
    );
  };
  if (!hit(n)) return null;

  const show = open || (!!q && depth < 5);
  const isNews = n.level === "news";
  const w = Math.max(150, 340 - depth * 26);

  return (
    <div className="l3-branch">
      <div
        className={`l3-card lv-${n.level}${picked === n.full_slug ? " picked" : ""}`}
        style={{
          ["--z" as any]: `${depth * 26}px`,
          ["--w" as any]: `${w}px`,
          ["--c" as any]: LEVEL_COLOR[n.level] ?? "var(--dim)",
        }}
        onClick={(e) => {
          e.stopPropagation();
          onPick(n);
          if (kids.length) setOpen((o) => !o);
        }}
      >
        <span className="l3-ico">{ICON[n.level] ?? "•"}</span>
        <span className="l3-name">
          {q
            ? n.name
                .split(new RegExp(`(${q.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")})`, "ig"))
                .map((p, i) =>
                  p.toLowerCase() === q.toLowerCase() ? <mark key={i}>{p}</mark> : p
                )
            : n.name}
        </span>
        {n.entity_short && <span className="l3-short">{n.entity_short}</span>}
        {total > 0 && (
          <span className={`l3-n${isNews ? " live" : ""}`}>{total}</span>
        )}
        {kids.length > 0 && <span className="l3-caret">{show ? "−" : "+"}</span>}
      </div>

      {show && kids.length > 0 && (
        <div className="l3-kids">
          {kids.map((c) => (
            <Card3D
              key={c.full_slug}
              n={c}
              depth={depth + 1}
              q={q}
              onPick={onPick}
              picked={picked}
            />
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
  const [rx, setRx] = useState(52);
  const [rz, setRz] = useState(-38);
  const [zoom, setZoom] = useState(0.78);
  const [flat, setFlat] = useState(false);
  const [picked, setPicked] = useState<FolderNode | null>(null);
  const drag = useRef<{ x: number; y: number; rx: number; rz: number } | null>(null);

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

  const onDown = (e: React.PointerEvent) => {
    if (flat) return;
    drag.current = { x: e.clientX, y: e.clientY, rx, rz };
    (e.target as HTMLElement).setPointerCapture?.(e.pointerId);
  };
  const onMove = (e: React.PointerEvent) => {
    if (!drag.current) return;
    const d = drag.current;
    setRx(Math.max(0, Math.min(84, d.rx - (e.clientY - d.y) * 0.32)));
    setRz(d.rz + (e.clientX - d.x) * 0.32);
  };
  const onUp = () => {
    drag.current = null;
  };

  return (
    <>
      <div className="hero-band">
        <div className="wrap">
          <h1 className="big">Folder structure</h1>
          <p className="lede">
            {doc.folders.length} folders holding{" "}
            {idx?.story_count.toLocaleString() ?? "3,606"} stories. Each depth is
            its own plane — drag to orbit, scroll to zoom, click to expand.
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
                  <b style={{ color: LEVEL_COLOR[k] }}>{stats[k] ?? 0}</b>
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
          <button className="ghost" onClick={() => setFlat((f) => !f)}>
            {flat ? "3D view" : "Flat view"}
          </button>
          {!flat && (
            <>
              <button
                className="ghost"
                onClick={() => { setRx(52); setRz(-38); setZoom(0.78); }}
              >
                Reset angle
              </button>
              <span className="hint">
                {Math.round(rx)}° / {Math.round(rz)}° · {Math.round(zoom * 100)}%
              </span>
            </>
          )}
        </div>

        <div className="legend">
          {[["region", "Region"], ["entity", "Entity"],
            ["department", "Department"], ["news", "News folder"]].map(([k, l]) => (
            <span key={k}>
              <span style={{ color: LEVEL_COLOR[k] }}>{ICON[k]}</span> {l}
            </span>
          ))}
        </div>

        <div
          className={`l3-stage${flat ? " flat" : ""}`}
          onPointerDown={onDown}
          onPointerMove={onMove}
          onPointerUp={onUp}
          onPointerLeave={onUp}
          onWheel={(e) => {
            if (flat) return;
            e.preventDefault();
            setZoom((z) => Math.max(0.32, Math.min(1.7, z - e.deltaY * 0.0011)));
          }}
        >
          <div
            className="l3-world"
            style={
              flat
                ? undefined
                : {
                    transform:
                      `rotateX(${rx}deg) rotateZ(${rz}deg) scale(${zoom})`,
                  }
            }
          >
            {doc.tree.map((n) => (
              <Card3D
                key={n.full_slug}
                n={n}
                depth={0}
                q={q}
                onPick={setPicked}
                picked={picked?.full_slug ?? null}
              />
            ))}
          </div>
        </div>

        {picked && (
          <div className="l3-panel">
            <button className="l3-close" onClick={() => setPicked(null)}>×</button>
            <span className="rv-label">{picked.level.replace("-", " ")}</span>
            <h3>{picked.name}</h3>
            <dl className="kv">
              <dt>Path</dt>
              <dd><code>{picked.display_path}</code></dd>
              <dt>Slug</dt>
              <dd><code>{picked.full_slug}</code></dd>
              {picked.region && (<><dt>Region</dt><dd>{picked.region}</dd></>)}
              {picked.entity && (<><dt>Entity</dt><dd>{picked.entity}</dd></>)}
              {picked.department && (<><dt>Department</dt><dd>{picked.department}</dd></>)}
              <dt>Stories here</dt>
              <dd>{picked.story_count ?? 0}</dd>
              <dt>Including children</dt>
              <dd>{deepCount(picked)}</dd>
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
