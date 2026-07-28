"use client";

import React from "react";
import type { MediaItem, RichNode } from "./types";

/**
 * Article-style rendering with real media.
 *
 * Images come straight off the live SharePoint site (resolved by
 * resolve_media_urls.py), so what you see is what the source page shows. Every
 * media block is labelled with its kind — IMAGE / GIF / VIDEO / IFRAME /
 * GALLERY — so it is obvious at a glance which component each one needs.
 */

export function kindOf(m: MediaItem): "gif" | "video" | "doc" | "image" {
  const f = (m.filename ?? m.local_filename ?? "").toLowerCase();
  if (m.media_type === "gif" || f.endsWith(".gif")) return "gif";
  if (m.media_type === "video" || /\.(mp4|mov|webm|m4v)$/.test(f)) return "video";
  if (/\.(pdf|docx?|xlsx?|pptx?|zip)$/.test(f)) return "doc";
  return "image";
}

export function Label({ kind, extra }: { kind: string; extra?: string }) {
  const icon: Record<string, string> = {
    image: "🖼", gif: "◉", video: "▶", iframe: "⧉", gallery: "▦", doc: "📄",
  };
  return (
    <span className={`mlabel ${kind}`}>
      {icon[kind] ?? "•"} {kind}
      {extra ? ` · ${extra}` : ""}
    </span>
  );
}

function Missing({ label, name }: { label: string; name: string }) {
  return (
    <div className="figure">
      <Label kind={label} extra="not resolved" />
      <div className="missing">
        <span className="ic">⚠</span>
        <span>
          <b>{name}</b>
          <br />
          No live URL — run <code>resolve_media_urls.py</code> for this story, or
          the file is gone from SharePoint.
        </span>
      </div>
    </div>
  );
}

/** One media item as an article figure. */
export function Figure({ m, role }: { m: MediaItem & { live_url?: string }; role?: string }) {
  const kind = kindOf(m);
  const name = m.filename ?? m.local_filename ?? "(unnamed)";
  const url = m.live_url;
  const cap = m.caption || m.alt || "";

  if (!url) return <Missing label={kind} name={name} />;

  if (kind === "video") {
    return (
      <figure className="figure">
        <Label kind="video" extra={role} />
        <video controls preload="metadata" src={url} />
        <figcaption>
          {cap} <code>{name}</code>
        </figcaption>
      </figure>
    );
  }
  if (kind === "doc") {
    return (
      <div className="figure">
        <Label kind="doc" extra={role} />
        <div className="missing">
          <span className="ic">📄</span>
          <span>
            <a href={url} target="_blank" rel="noreferrer">
              <b>{name}</b>
            </a>
            {cap ? <><br />{cap}</> : null}
          </span>
        </div>
      </div>
    );
  }
  return (
    <figure className="figure">
      <Label kind={kind} extra={role} />
      {/* eslint-disable-next-line @next/next/no-img-element */}
      <img src={url} alt={m.alt ?? ""} loading="lazy" />
      {(cap || name) && (
        <figcaption>
          {cap} {cap ? "· " : ""}
          <code>{name}</code>
        </figcaption>
      )}
    </figure>
  );
}

export function Gallery({ items }: { items: (MediaItem & { live_url?: string })[] }) {
  const withUrl = items.filter((m) => m.live_url);
  if (!withUrl.length) return null;
  return (
    <div className="figure">
      <Label kind="gallery" extra={`${withUrl.length} images`} />
      <div className="gallery-grid">
        {withUrl.map((m, i) => (
          // eslint-disable-next-line @next/next/no-img-element
          <img key={i} src={m.live_url} alt={m.alt ?? ""} loading="lazy"
               title={m.filename ?? ""} />
        ))}
      </div>
    </div>
  );
}

function youtubeEmbed(u: string) {
  const id =
    u.match(/youtube\.com\/embed\/([\w-]{6,})/)?.[1] ??
    u.match(/[?&]v=([\w-]{6,})/)?.[1] ??
    u.match(/youtu\.be\/([\w-]{6,})/)?.[1];
  return id ? `https://www.youtube.com/embed/${id}` : null;
}

export function Frame({ url, kind = "iframe" }: { url: string; kind?: string }) {
  const yt = youtubeEmbed(url);
  return (
    <div className="figure">
      <Label kind={yt ? "video" : kind} extra={yt ? "YouTube" : "embed"} />
      <div className="frame-wrap">
        <iframe
          src={yt ?? url}
          allow="accelerometer; autoplay; clipboard-write; encrypted-media; gyroscope; picture-in-picture"
          allowFullScreen
          referrerPolicy="no-referrer"
          title={url}
        />
      </div>
      <figcaption style={{ fontSize: 12, color: "var(--dim)", marginTop: 6 }}>
        <a href={url} target="_blank" rel="noreferrer">
          <code>{url.slice(0, 100)}</code>
        </a>
      </figcaption>
    </div>
  );
}

export function Tweet({ url }: { url: string }) {
  return (
    <div className="figure">
      <Label kind="iframe" extra="tweet" />
      <div className="tweet">
        🐦{" "}
        <a href={url} target="_blank" rel="noreferrer">
          {url}
        </a>
      </div>
    </div>
  );
}

/* ------------------------------------------------------------ rich text */

function applyMarks(text: string, marks?: RichNode["marks"]): React.ReactNode {
  let el: React.ReactNode = text;
  for (const m of marks ?? []) {
    const a = (m.attrs ?? {}) as Record<string, string>;
    if (m.type === "bold") el = <strong>{el}</strong>;
    else if (m.type === "italic") el = <em>{el}</em>;
    else if (m.type === "underline") el = <u>{el}</u>;
    else if (m.type === "strike") el = <s>{el}</s>;
    else if (m.type === "superscript") el = <sup>{el}</sup>;
    else if (m.type === "subscript") el = <sub>{el}</sub>;
    else if (m.type === "code") el = <code>{el}</code>;
    else if (m.type === "link") {
      const href = a.href || a.url || "#";
      el = (
        <a href={href} target="_blank" rel="noreferrer" title={href}>
          {el}
        </a>
      );
    }
  }
  return el;
}

type Ctx = { srcToLive: Record<string, string> };

function Bloks({ body, ctx }: { body: any[]; ctx: Ctx }) {
  return (
    <>
      {body.map((b, i) => {
        if (b?.component === "video_embed" && b.embed_url)
          return <Frame key={i} url={b.embed_url} />;
        if (b?.component === "twitter_embed" && b.tweet_url)
          return <Tweet key={i} url={b.tweet_url} />;
        return (
          <div className="figure" key={i}>
            <Label kind="iframe" extra={b?.component ?? "blok"} />
            <div className="missing">
              <span className="ic">⧉</span>
              <code>{JSON.stringify(b).slice(0, 240)}</code>
            </div>
          </div>
        );
      })}
    </>
  );
}

export function Nodes({ nodes, ctx }: { nodes?: RichNode[]; ctx: Ctx }) {
  return (
    <>
      {(nodes ?? []).map((n, i) => (
        <Node node={n} ctx={ctx} key={i} />
      ))}
    </>
  );
}

function Node({ node, ctx }: { node: RichNode; ctx: Ctx }): React.ReactElement | null {
  const t = node.type;
  const kids = <Nodes nodes={node.content} ctx={ctx} />;

  if (t === "text") return <>{applyMarks(node.text ?? "", node.marks)}</>;
  if (t === "hard_break") return <br />;
  if (t === "horizontal_rule") return <hr />;
  if (t === "paragraph") return <p>{kids}</p>;
  if (t === "heading") {
    const lvl = Math.min(Math.max(Number(node.attrs?.level ?? 2), 1), 6);
    const H = `h${lvl}` as keyof React.JSX.IntrinsicElements;
    return <H>{kids}</H>;
  }
  if (t === "bullet_list") return <ul>{kids}</ul>;
  if (t === "ordered_list") return <ol>{kids}</ol>;
  if (t === "list_item") return <li>{kids}</li>;
  if (t === "blockquote") return <blockquote>{kids}</blockquote>;
  if (t === "table") return <table><tbody>{kids}</tbody></table>;
  if (t === "tableRow") return <tr>{kids}</tr>;
  if (t === "tableHeader") return <th>{kids}</th>;
  if (t === "tableCell") return <td>{kids}</td>;
  if (t === "blok") return <Bloks body={node.attrs?.body ?? []} ctx={ctx} />;
  if (t === "image") {
    const src = node.attrs?.src ?? "";
    const live = ctx.srcToLive[src] ?? (src.startsWith("http") ? src : "");
    const name = src.split("/").pop() ?? "";
    const isGif = /\.gif$/i.test(name);
    if (!live) return <Missing label={isGif ? "gif" : "image"} name={name} />;
    return (
      <figure className="figure">
        <Label kind={isGif ? "gif" : "image"} extra="inline" />
        {/* eslint-disable-next-line @next/next/no-img-element */}
        <img src={live} alt={node.attrs?.alt ?? ""} loading="lazy" />
        {node.attrs?.alt && <figcaption>{node.attrs.alt}</figcaption>}
      </figure>
    );
  }
  if (t === "doc" || node.content) return <>{kids}</>;
  return null;
}

export function Prose({ doc, srcToLive }: { doc: RichNode; srcToLive: Record<string, string> }) {
  return (
    <div className="prose">
      <Nodes nodes={doc?.content} ctx={{ srcToLive }} />
    </div>
  );
}
