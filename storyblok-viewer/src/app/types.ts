export type Counts = {
  chars: number;
  words: number;
  media: number;
  richtext_media: number;
  links: number;
  images_inline: number;
  shares: number;
};

export type Story = {
  id: number;
  seq: string;
  title: string;
  date: string;
  year: string;
  writer: string;
  author: string;
  category: string;
  region: string;
  entity: string;
  department: string;
  placement: string;
  folder: string;
  is_global: boolean;
  elements: string[];
  counts: Counts;
  status: string;
  sb_story_id: number | null;
  sb_slug: string;
  excerpt: string;
  /** live SharePoint URL of the banner image, when resolved */
  hero?: string;
  /** first resolvable image, used for the list thumbnail */
  thumb?: string;
};

export type Index = {
  story_count: number;
  element_labels: Record<string, string>;
  facets: Record<string, Record<string, number>>;
  stories: Story[];
};

export type MediaItem = {
  role?: string;
  media_type?: string;
  filename?: string;
  local_filename?: string;
  src?: string;
  local_src?: string;
  caption?: string;
  alt?: string;
  source_key?: string;
  live_url?: string;
};

export type RichMark = { type: string; attrs?: Record<string, unknown> };

export type RichNode = {
  type?: string;
  text?: string;
  marks?: RichMark[];
  attrs?: Record<string, any>;
  content?: RichNode[];
};

export type Detail = Story & {
  summary: string;
  subtitle: string;
  banner_caption: string;
  sharepoint_url: string;
  sb_editor_url: string;
  sharepoint_page: string;
  media_urls_fetched: boolean;
  richtext: RichNode;
  media: MediaItem[];
  richtext_media: MediaItem[];
  links: { href: string; text: string }[];
  shares: string[];
  page_iframes: string[];
  unmatched_page_images: string[];
  src_to_live: Record<string, string>;
  node_counts: Record<string, number>;
  mark_counts: Record<string, number>;
  blok_counts: Record<string, number>;
  extensions: Record<string, number>;
  pull_quote: { type?: string; component_type?: string; author?: string } | null;
};

/** Facet groups, in sidebar order. `open` = expanded on first load. */
export const FACET_ORDER: { key: string; label: string; open?: boolean }[] = [
  { key: "elements", label: "Elements / components", open: true },
  { key: "region", label: "Region", open: true },
  { key: "entity", label: "Entity" },
  { key: "department", label: "Department" },
  { key: "placement", label: "Placement" },
  { key: "writer", label: "Writer" },
  { key: "category", label: "SharePoint category" },
  { key: "year", label: "Year" },
  { key: "status", label: "Migration status" },
];

/** Element keys worth surfacing as a chip on a list row. */
export const HERO_ELEMENTS = [
  "video_embed",
  "video_file",
  "twitter_embed",
  "iframe_embed",
  "gallery",
  "gif",
  "table",
  "pdf",
  "doc",
  "inline_image",
  "urdu",
  "thumbnail",
  "no_media",
];
