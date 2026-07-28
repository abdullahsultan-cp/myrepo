"use client";

import React from "react";
import type { RichNode, MediaItem } from "./types";

/**
 * Renders a Storyblok richtext document.
 *
 * Media is not rendered as an image: the SharePoint bundle is not part of the
 * repo, so every src points at a file that does not exist here. A labelled
 * placeholder showing role, type and filename is more useful for review than a
 * broken image — it says exactly which asset has to be uploaded.
 */

function marksToNode(text: string, marks?: RichNode["marks"]): React.ReactNode {
  let el: React.ReactNode = text;
  for (const m of marks ?? []) {
    switch (m.type) {
      case "bold":
        el = <strong>{el}</strong>;
        break;
      case "italic":
        el = <em>{el}</em>;
        break;
      case "underline":
        el = <u>{el}</u>;
        break;
      case "strike":
        el = <s>{el}</s>;
        break;
      case "superscript":
        el = <sup>{el}</sup>;
        break;
      case "subscript":
        el = <sub>{el}</sub>;
        break;
      case "code":
        el = <code>{el}</code>;
        break;
      case "link": {
        const a = (m.attrs ?? {}) as Record<string, string>;
        const href = a.href || a.url || "#";
        el = (
          <a href={href} target="_blank" rel="noreferrer" title={href}>
            {el}
          </a>
        );
        break;
      }
      default:
        break;
    }
  }
  return el;
}

function Placeholder({ src, alt }: { src?: string; alt?: string }) {
  const name = (src ?? "").split("/").pop() || "(no src)";
  return (
    <span className="ph">
      <b>inline image</b> — {name}
      {alt ? ` · alt: ${alt}` : ""}
    </span>
  );
}

function Blok({ body }: { body: any[] }) {
  return (
    <>
      {body.map((b, i) => {
        const c = b?.component;
        if (c === "video_embed") {
          return (
            <div className="embed" key={i}>
              <b>▶ video_embed</b> ({b.provider ?? "?"}) —{" "}
              <a href={b.embed_url} target="_blank" rel="noreferrer">
                {b.embed_url}
              </a>
            </div>
          );
        }
        if (c === "twitter_embed") {
          return (
            <div className="embed" key={i}>
              <b>🐦 twitter_embed</b> —{" "}
              <a href={b.tweet_url} target="_blank" rel="noreferrer">
                {b.tweet_url}
              </a>
            </div>
          );
        }
        return (
          <div className="embed" key={i}>
            <b>{c ?? "unknown blok"}</b>
            <br />
            <code>{JSON.stringify(b).slice(0, 220)}</code>
          </div>
        );
      })}
    </>
  );
}

export function Nodes({ nodes }: { nodes?: RichNode[] }): React.ReactElement {
  return (
    <>
      {(nodes ?? []).map((n, i) => (
        <Node node={n} key={i} />
      ))}
    </>
  );
}

function Node({ node }: { node: RichNode }): React.ReactElement | null {
  const t = node.type;

  if (t === "text") return <>{marksToNode(node.text ?? "", node.marks)}</>;
  if (t === "hard_break") return <br />;
  if (t === "horizontal_rule") return <hr />;
  if (t === "paragraph")
    return (
      <p>
        <Nodes nodes={node.content} />
      </p>
    );
  if (t === "heading") {
    const lvl = Math.min(Math.max(Number(node.attrs?.level ?? 2), 1), 6);
    const H = `h${lvl}` as keyof React.JSX.IntrinsicElements;
    return (
      <H>
        <Nodes nodes={node.content} />
      </H>
    );
  }
  if (t === "bullet_list")
    return (
      <ul>
        <Nodes nodes={node.content} />
      </ul>
    );
  if (t === "ordered_list")
    return (
      <ol>
        <Nodes nodes={node.content} />
      </ol>
    );
  if (t === "list_item")
    return (
      <li>
        <Nodes nodes={node.content} />
      </li>
    );
  if (t === "blockquote")
    return (
      <blockquote>
        <Nodes nodes={node.content} />
      </blockquote>
    );
  if (t === "image")
    return <Placeholder src={node.attrs?.src} alt={node.attrs?.alt} />;
  if (t === "blok") return <Blok body={node.attrs?.body ?? []} />;
  if (t === "table")
    return (
      <table>
        <tbody>
          <Nodes nodes={node.content} />
        </tbody>
      </table>
    );
  if (t === "tableRow")
    return (
      <tr>
        <Nodes nodes={node.content} />
      </tr>
    );
  if (t === "tableHeader")
    return (
      <th>
        <Nodes nodes={node.content} />
      </th>
    );
  if (t === "tableCell")
    return (
      <td>
        <Nodes nodes={node.content} />
      </td>
    );
  if (t === "doc" || node.content)
    return (
      <>
        <Nodes nodes={node.content} />
      </>
    );
  return null;
}

export function MediaList({ items }: { items: MediaItem[] }) {
  if (!items.length) return <p style={{ color: "var(--fg-faint)" }}>none</p>;
  return (
    <table className="grid">
      <thead>
        <tr>
          <th>role</th>
          <th>type</th>
          <th>filename</th>
          <th>caption</th>
        </tr>
      </thead>
      <tbody>
        {items.map((m, i) => (
          <tr key={i}>
            <td>{m.role ?? "—"}</td>
            <td>{m.media_type ?? "—"}</td>
            <td>
              <code>{m.filename ?? m.local_filename ?? "—"}</code>
            </td>
            <td>{m.caption ?? ""}</td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}

export function RichText({ doc }: { doc: RichNode }) {
  return (
    <div className="rt">
      <Nodes nodes={doc?.content} />
    </div>
  );
}
