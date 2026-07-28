"use client";

import Link from "next/link";
import { useParams } from "next/navigation";
import React from "react";
import { Figure, Frame, Gallery, Prose, Tweet, kindOf } from "../../Media";
import { fmtDate, readTime, related, useIndex, useStory } from "../../lib";
import type { Story } from "../../types";

/**
 * News detail page, rendered the way the site will render it from the
 * news_article JSON: hero banner, byline, share rail, body bloks in order,
 * then related cards.
 */

function ShareRail() {
  return (
    <div className="share">
      <span className="share-label">Share</span>
      {["in", "X", "f", "✉"].map((s) => (
        <span className="share-btn" key={s} aria-hidden>
          {s}
        </span>
      ))}
    </div>
  );
}

function Related({ items }: { items: Story[] }) {
  if (!items.length) return null;
  return (
    <section className="related">
      <div className="wrap">
        <h2 className="sec-title">Similar stories</h2>
        <div className="cardgrid three">
          {items.map((s) => (
            <Link href={`/story/${s.id}`} className="card" key={s.id}>
              <div className="card-media">
                {s.thumb ? (
                  // eslint-disable-next-line @next/next/no-img-element
                  <img src={s.thumb} alt="" loading="lazy" />
                ) : (
                  <div className="card-noimg">no image</div>
                )}
              </div>
              <div className="card-body">
                <div className="card-meta">
                  {s.entity && <span className="k">{s.entity}</span>}
                </div>
                <h3 className="card-title">{s.title}</h3>
                <div className="card-foot">
                  <span>{fmtDate(s.date)}</span>
                </div>
              </div>
            </Link>
          ))}
        </div>
      </div>
    </section>
  );
}

export default function StoryPage() {
  const params = useParams<{ id: string }>();
  const id = params?.id;
  const { story: d, err } = useStory(id ?? null);
  const { idx } = useIndex();

  if (err) return <div className="hollow">{err}</div>;
  if (!d) return <div className="hollow">Loading story…</div>;

  const banner = d.media.find((m) => m.role === "banner");
  const medium = d.media.filter((m) => m.role === "medium");
  const inline = d.media.filter((m) => m.role === "richtext");
  const videos = d.media.filter((m) => String(m.role ?? "").startsWith("video"));
  const docs = [...d.media, ...d.richtext_media].filter((m) => kindOf(m) === "doc");
  const gallery = inline.filter((m) => m.live_url).length >= 3 ? inline : [];
  const rel = idx ? related(idx.stories, d as unknown as Story, 3) : [];

  return (
    <article className="story">
      {/* -------------------------------------------------------- hero */}
      {banner?.live_url ? (
        <div className="story-hero">
          {/* eslint-disable-next-line @next/next/no-img-element */}
          <img src={banner.live_url} alt={banner.alt ?? ""} />
          <div className="story-hero-fade" />
        </div>
      ) : null}

      <div className="wrap narrow">
        <div className="story-kicker">
          {d.region && <span className="k">{d.region}</span>}
          {d.entity && <span className="k soft">{d.entity}</span>}
          {d.department && <span className="k soft">{d.department}</span>}
          {d.category && <span className="k soft">{d.category}</span>}
        </div>

        <h1 className="story-title">{d.title}</h1>
        {d.subtitle && <p className="story-sub">{d.subtitle}</p>}

        <div className="story-byline">
          <div className="story-by">
            {d.writer && <span className="who">{d.writer}</span>}
            <span className="when">
              {fmtDate(d.date) || "no date"} · {readTime(d.counts.words)}
            </span>
          </div>
          <ShareRail />
        </div>

        {banner?.caption && <p className="hero-cap">{banner.caption}</p>}

        {d.summary && <p className="story-lede">{d.summary}</p>}

        <Prose doc={d.richtext} srcToLive={d.src_to_live} />

        {gallery.length > 0 && <Gallery items={gallery} />}
        {medium.map((m, i) => <Figure key={`m${i}`} m={m} role="medium" />)}
        {videos.map((m, i) => <Figure key={`v${i}`} m={m} role={m.role} />)}
        {docs.map((m, i) => <Figure key={`d${i}`} m={m} role="attachment" />)}
        {d.pull_quote?.component_type === "iframe_embed" &&
          d.page_iframes.map((u, i) => <Frame key={`f${i}`} url={u} />)}

        {/* --------------------------------------------- review footer */}
        <div className="story-review">
          <span className="rv-label">Review links</span>
          <div className="rv-links">
            {d.sharepoint_url && (
              <a className="btn primary" href={d.sharepoint_url} target="_blank" rel="noreferrer">
                ↗ SharePoint original
              </a>
            )}
            {d.sb_editor_url && (
              <a className="btn" href={d.sb_editor_url} target="_blank" rel="noreferrer">
                ✎ Storyblok editor
              </a>
            )}
            <Link className="btn" href={`/inspect?id=${d.id}`}>
              ⚙ Inspect data
            </Link>
          </div>
          <div className="rv-meta">
            <span>#{d.id}</span>
            <span><code>{d.seq}</code></span>
            <span><code>{d.folder || "no folder"}</code></span>
            {!d.media_urls_fetched && (
              <span className="warnpill">media URLs not resolved yet</span>
            )}
          </div>
        </div>
      </div>

      <Related items={rel} />
    </article>
  );
}
