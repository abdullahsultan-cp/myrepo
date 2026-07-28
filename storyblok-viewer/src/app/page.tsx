"use client";

import Link from "next/link";
import React, { useMemo } from "react";
import { fmtDate, useIndex } from "./lib";
import type { Story } from "./types";

/** Overview: where the migration stands, and the way in to everything else. */

function Bar({
  rows,
  total,
  labels,
}: {
  rows: [string, number][];
  total: number;
  labels?: Record<string, string>;
}) {
  const max = Math.max(...rows.map(([, n]) => n), 1);
  return (
    <div className="barlist">
      {rows.map(([k, n]) => (
        <div className="barrow" key={k}>
          <span className="barlabel" title={labels?.[k] ?? k}>
            {labels?.[k] ?? k}
          </span>
          <span className="bartrack">
            <span className="barfill" style={{ width: `${(n / max) * 100}%` }} />
          </span>
          <span className="barnum">{n.toLocaleString()}</span>
        </div>
      ))}
    </div>
  );
}

export default function Home() {
  const { idx, err } = useIndex();

  const recent = useMemo(
    () =>
      idx
        ? [...idx.stories]
            .sort((a, b) => (b.date || "").localeCompare(a.date || ""))
            .filter((s) => s.thumb)
            .slice(0, 6)
        : [],
    [idx]
  );

  if (err) return <div className="hollow">{err}</div>;
  if (!idx) return <div className="hollow">Loading…</div>;

  const withMedia = idx.stories.filter((s) => !s.elements.includes("no_media")).length;
  const resolved = idx.stories.filter((s) => s.thumb).length;
  const inSB = idx.stories.filter((s) => s.status === "verified").length;

  const el = Object.entries(idx.facets.elements ?? {}) as [string, number][];
  const structural = el
    .filter(([k]) =>
      ["video_embed", "video_file", "twitter_embed", "iframe_embed", "gallery",
       "gif", "table", "pdf", "doc", "inline_image", "thumbnail", "urdu",
       "bullet_list", "ordered_list", "heading", "blockquote", "pull_quote",
       "superscript"].includes(k)
    )
    .sort((a, b) => b[1] - a[1]);

  return (
    <>
      <div className="hero-band tall">
        <div className="wrap">
          <span className="eyebrow">SharePoint → Storyblok</span>
          <h1 className="big">
            {idx.story_count.toLocaleString()} news stories,
            <br />
            ready to review.
          </h1>
          <p className="lede">
            Everything the migration produced, in one place: read the articles as
            they will look, browse the folder structure, and check any story
            against its SharePoint original.
          </p>
          <div className="cta">
            <Link className="solid" href="/archive">Browse the archive →</Link>
            <Link className="ghost" href="/tree">See the folder structure</Link>
          </div>
        </div>
      </div>

      <div className="wrap">
        <div className="tiles">
          {[
            [idx.story_count.toLocaleString(), "stories migrated"],
            [withMedia.toLocaleString(), "have media"],
            [resolved.toLocaleString(), "images resolved"],
            [String(inSB), "uploaded to Storyblok"],
          ].map(([n, l]) => (
            <div className="tile" key={l}>
              <b>{n}</b>
              <span>{l}</span>
            </div>
          ))}
        </div>

        {resolved < withMedia && (
          <div className="notice">
            <b>Images still resolving.</b> {resolved.toLocaleString()} of{" "}
            {withMedia.toLocaleString()} stories with media have their live
            SharePoint image URLs. Run{" "}
            <code>Resume AKU media.cmd</code> on the Desktop to continue — stories
            without a resolved image show a placeholder until then.
          </div>
        )}

        {recent.length > 0 && (
          <>
            <h2 className="sec-title">Latest stories</h2>
            <div className="cardgrid three">
              {recent.map((s: Story) => (
                <Link href={`/story/${s.id}`} className="card" key={s.id}>
                  <div className="card-media">
                    {/* eslint-disable-next-line @next/next/no-img-element */}
                    <img src={s.thumb} alt="" loading="lazy" />
                  </div>
                  <div className="card-body">
                    <div className="card-meta">
                      {s.region && <span className="k">{s.region}</span>}
                      {s.entity && <span>{s.entity}</span>}
                    </div>
                    <h3 className="card-title">{s.title}</h3>
                    <div className="card-foot">
                      <span>{fmtDate(s.date)}</span>
                    </div>
                  </div>
                </Link>
              ))}
            </div>
          </>
        )}

        <div className="split">
          <section>
            <h2 className="sec-title">Where the stories live</h2>
            <Bar
              rows={(Object.entries(idx.facets.region ?? {}) as [string, number][])
                .sort((a, b) => b[1] - a[1])}
              total={idx.story_count}
            />
            <h2 className="sec-title">Biggest entities</h2>
            <Bar
              rows={(Object.entries(idx.facets.entity ?? {}) as [string, number][])
                .sort((a, b) => b[1] - a[1])
                .slice(0, 10)}
              total={idx.story_count}
            />
          </section>
          <section>
            <h2 className="sec-title">
              What the stories contain
              <span className="sec-note">
                this is the component inventory — each row is something a
                component has to handle
              </span>
            </h2>
            <Bar rows={structural} total={idx.story_count} labels={idx.element_labels} />
          </section>
        </div>
      </div>
    </>
  );
}
