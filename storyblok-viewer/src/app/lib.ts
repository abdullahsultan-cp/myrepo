"use client";

import { useEffect, useState } from "react";
import type { Detail, Index, Story } from "./types";

/** Shared client-side data loading. index.json is 2.5 MB, so cache it. */

let _index: Index | null = null;
let _pending: Promise<Index> | null = null;

export function loadIndex(): Promise<Index> {
  if (_index) return Promise.resolve(_index);
  if (!_pending) {
    _pending = fetch("/data/index.json")
      .then((r) => {
        if (!r.ok) throw new Error(`index.json → HTTP ${r.status}`);
        return r.json();
      })
      .then((j: Index) => {
        _index = j;
        return j;
      });
  }
  return _pending;
}

export function useIndex() {
  const [idx, setIdx] = useState<Index | null>(_index);
  const [err, setErr] = useState("");
  useEffect(() => {
    loadIndex().then(setIdx).catch((e) => setErr(String(e)));
  }, []);
  return { idx, err };
}

export function useStory(id: string | number | null) {
  const [d, setD] = useState<Detail | null>(null);
  const [err, setErr] = useState("");
  useEffect(() => {
    if (id == null || id === "") return;
    setD(null);
    setErr("");
    fetch(`/data/stories/${id}.json`)
      .then((r) => {
        if (!r.ok) throw new Error(`story ${id} → HTTP ${r.status}`);
        return r.json();
      })
      .then(setD)
      .catch((e) => setErr(String(e)));
  }, [id]);
  return { story: d, err };
}

export type FolderNode = {
  level: string;
  name: string;
  slug: string;
  full_slug: string;
  parent_full_slug: string | null;
  display_path: string;
  region: string | null;
  entity: string | null;
  entity_short: string | null;
  department: string | null;
  expected_news_count: number;
  story_count?: number;
  children?: FolderNode[];
};

export type FolderDoc = {
  meta: { counts: Record<string, any> };
  folders: FolderNode[];
  tree: FolderNode[];
};

export function useFolders() {
  const [doc, setDoc] = useState<FolderDoc | null>(null);
  const [err, setErr] = useState("");
  useEffect(() => {
    fetch("/data/folders.json")
      .then((r) => {
        if (!r.ok) throw new Error(`folders.json → HTTP ${r.status}`);
        return r.json();
      })
      .then(setDoc)
      .catch((e) => setErr(String(e)));
  }, []);
  return { doc, err };
}

/* ------------------------------------------------------------- helpers */

export function fmtDate(iso: string) {
  if (!iso) return "";
  const d = new Date(iso + "T00:00:00");
  if (isNaN(+d)) return iso;
  return d.toLocaleDateString("en-GB", {
    day: "numeric",
    month: "long",
    year: "numeric",
  });
}

/**
 * Must match scripts/migrate/build_payload.py exactly, or the viewer disagrees
 * with what was uploaded. 238 wpm is the meta-analytic mean for silent reading
 * of English non-fiction (Brysbaert 2019); each image adds 12s.
 */
export const WPM = 238;
export const SECONDS_PER_IMAGE = 12;

export function readTime(words: number, images = 0) {
  const seconds = (words / WPM) * 60 + images * SECONDS_PER_IMAGE;
  return `${Math.max(1, Math.ceil(seconds / 60))} min read`;
}

/** Newest-first, then by id so ordering is stable. */
export function byNewest(a: Story, b: Story) {
  const c = (b.date || "").localeCompare(a.date || "");
  return c !== 0 ? c : b.id - a.id;
}

/** Related picks: same entity first, then same region. */
export function related(all: Story[], s: Story, n = 3) {
  const pool = all.filter((x) => x.id !== s.id);
  const score = (x: Story) =>
    (x.entity && x.entity === s.entity ? 4 : 0) +
    (x.department && x.department === s.department ? 3 : 0) +
    (x.region === s.region ? 2 : 0) +
    (x.thumb ? 1 : 0);
  return pool
    .map((x) => [score(x), x] as const)
    .filter(([sc]) => sc > 0)
    .sort((a, b) => b[0] - a[0] || byNewest(a[1], b[1]))
    .slice(0, n)
    .map(([, x]) => x);
}
