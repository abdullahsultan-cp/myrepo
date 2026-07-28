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
};

export type Detail = Story & {
  summary: string;
  subtitle: string;
  banner_caption: string;
  sharepoint_url: string;
  sb_editor_url: string;
  richtext: RichNode;
  media: MediaItem[];
  richtext_media: MediaItem[];
  links: { href: string; text: string }[];
  shares: string[];
  node_counts: Record<string, number>;
  mark_counts: Record<string, number>;
  blok_counts: Record<string, number>;
  extensions: Record<string, number>;
  pull_quote: { type?: string; component_type?: string; author?: string } | null;
};

export type RichMark = { type: string; attrs?: Record<string, unknown> };

export type RichNode = {
  type?: string;
  text?: string;
  marks?: RichMark[];
  attrs?: Record<string, any>;
  content?: RichNode[];
};

/** Facets rendered in the sidebar, in display order. */
export const FACET_ORDER: { key: keyof Story | "elements"; label: string }[] = [
  { key: "elements", label: "Elements / components" },
  { key: "region", label: "Region" },
  { key: "entity", label: "Entity" },
  { key: "department", label: "Department" },
  { key: "placement", label: "Placement" },
  { key: "writer", label: "Writer" },
  { key: "category", label: "SharePoint category" },
  { key: "year", label: "Year" },
  { key: "status", label: "Migration status" },
];
