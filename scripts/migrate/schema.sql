-- AKU news -> Storyblok migration tracking
--
-- Answers "what is done, what is not, and what went wrong" for 3606 stories and
-- ~3421 media files, and keeps the internal-link table needed to rewrite
-- SharePoint links once every story has a Storyblok id.
--
-- Idempotent: safe to re-run. Nothing here is dropped automatically.

CREATE SCHEMA IF NOT EXISTS migration;
SET search_path TO migration, public;

-- ---------------------------------------------------------------- runs
CREATE TABLE IF NOT EXISTS run (
    id              serial PRIMARY KEY,
    mode            text        NOT NULL,          -- dry-run | upload | verify
    space_id        text,
    folder_prefix   text,                          -- e.g. news/rabee
    note            text,
    started_at      timestamptz NOT NULL DEFAULT now(),
    finished_at     timestamptz,
    stories_ok      integer     NOT NULL DEFAULT 0,
    stories_failed  integer     NOT NULL DEFAULT 0,
    assets_ok       integer     NOT NULL DEFAULT 0,
    assets_failed   integer     NOT NULL DEFAULT 0
);

-- ---------------------------------------------------------------- stories
CREATE TABLE IF NOT EXISTS story (
    sharepoint_id   integer PRIMARY KEY,
    sequence_number text,
    title           text    NOT NULL,
    published_date  date,

    -- taxonomy, from the taxonomy stage
    region          text,
    entity          text,
    entity_short    text,
    department      text,
    placement       text,                          -- global|region|entity|entity-department
    surface_global  boolean NOT NULL DEFAULT false,
    region_source   text,
    entity_source   text,

    -- final destination once the real tree exists
    target_folder   text,
    target_slug     text,
    target_full_slug text,

    -- where this run actually put it (test runs use a different prefix)
    upload_folder   text,
    upload_full_slug text,

    scenarios       text[]  NOT NULL DEFAULT '{}', -- features this story proves
    is_sample       boolean NOT NULL DEFAULT false,

    status          text    NOT NULL DEFAULT 'pending',
    attempts        integer NOT NULL DEFAULT 0,
    payload_hash    text,                          -- skip re-upload when unchanged
    sb_story_id     bigint,
    sb_uuid         uuid,
    sb_parent_id    bigint,
    error           text,
    uploaded_at     timestamptz,
    verified_at     timestamptz,
    created_at      timestamptz NOT NULL DEFAULT now(),
    updated_at      timestamptz NOT NULL DEFAULT now(),

    CONSTRAINT story_status_ck CHECK (status IN
        ('pending','building','built','uploading','uploaded','verified',
         'failed','skipped'))
);

CREATE INDEX IF NOT EXISTS story_status_idx    ON story (status);
CREATE INDEX IF NOT EXISTS story_sample_idx    ON story (is_sample) WHERE is_sample;
CREATE INDEX IF NOT EXISTS story_scenarios_idx ON story USING gin (scenarios);
CREATE UNIQUE INDEX IF NOT EXISTS story_sb_id_idx
    ON story (sb_story_id) WHERE sb_story_id IS NOT NULL;

-- ---------------------------------------------------------------- assets
CREATE TABLE IF NOT EXISTS asset (
    id              bigserial PRIMARY KEY,
    sharepoint_id   integer NOT NULL REFERENCES story(sharepoint_id)
                        ON DELETE CASCADE,
    role            text    NOT NULL,              -- banner|medium|thumbnail|video1..3|richtext
    media_type      text,                          -- image|gif|video|other
    source_filename text    NOT NULL,
    source_path     text,                          -- resolved path under assets/
    source_url      text,                          -- for rich-text media still remote
    caption         text,
    alt             text,

    status          text    NOT NULL DEFAULT 'pending',
    exists_on_disk  boolean,
    content_type    text,
    bytes           bigint,
    sha256          text,

    sb_asset_id     bigint,
    sb_filename     text,                          -- https://a.storyblok.com/...
    sb_folder_id    bigint,
    error           text,
    uploaded_at     timestamptz,

    CONSTRAINT asset_status_ck CHECK (status IN
        ('pending','missing','uploading','uploaded','reused','failed','skipped')),
    CONSTRAINT asset_unique UNIQUE (sharepoint_id, role, source_filename)
);

CREATE INDEX IF NOT EXISTS asset_status_idx ON asset (status);
CREATE INDEX IF NOT EXISTS asset_story_idx  ON asset (sharepoint_id);
-- one upload per distinct source file, reused across stories
CREATE INDEX IF NOT EXISTS asset_sha_idx    ON asset (sha256)
    WHERE sha256 IS NOT NULL;

-- ---------------------------------------------------------------- links
-- Every anchor found in the body. Internal ones are rewritten in a second pass
-- once all stories have Storyblok ids, so this table IS the work queue.
CREATE TABLE IF NOT EXISTS link (
    id              bigserial PRIMARY KEY,
    sharepoint_id   integer NOT NULL REFERENCES story(sharepoint_id)
                        ON DELETE CASCADE,
    kind            text    NOT NULL,              -- internal|external|document|
                                                   -- anchor|email|tel|other
    raw_href        text    NOT NULL,
    link_text       text,
    occurrences     integer NOT NULL DEFAULT 1,

    -- resolution, filled by the link pass
    target_sharepoint_id integer,
    target_sb_story_id   bigint,
    target_sb_uuid       uuid,
    target_full_slug     text,
    rewritten_href       text,
    resolved             boolean NOT NULL DEFAULT false,
    resolution_method    text,                     -- exact-url|slug-match|
                                                   -- asset|manual|unresolved
    notes                text,
    CONSTRAINT link_kind_ck CHECK (kind IN
        ('internal','external','document','anchor','email','tel','other','empty'))
);

CREATE INDEX IF NOT EXISTS link_kind_idx     ON link (kind);
CREATE INDEX IF NOT EXISTS link_resolved_idx ON link (resolved) WHERE NOT resolved;
CREATE INDEX IF NOT EXISTS link_story_idx    ON link (sharepoint_id);
CREATE INDEX IF NOT EXISTS link_href_idx     ON link (raw_href);

-- ---------------------------------------------------------------- share refs
-- AdditionalEntity: show this story under another entity, view only.
CREATE TABLE IF NOT EXISTS share_target (
    id              bigserial PRIMARY KEY,
    sharepoint_id   integer NOT NULL REFERENCES story(sharepoint_id)
                        ON DELETE CASCADE,
    ref_region      text,
    ref_entity      text,
    ref_full_slug   text,
    ref_sb_story_id bigint,
    CONSTRAINT share_unique UNIQUE (sharepoint_id, ref_full_slug)
);

-- ---------------------------------------------------------------- audit
CREATE TABLE IF NOT EXISTS event (
    id              bigserial PRIMARY KEY,
    run_id          integer REFERENCES run(id) ON DELETE SET NULL,
    sharepoint_id   integer,
    level           text    NOT NULL DEFAULT 'info',  -- info|warn|error
    stage           text,
    message         text    NOT NULL,
    detail          jsonb,
    at              timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS event_story_idx ON event (sharepoint_id);
CREATE INDEX IF NOT EXISTS event_level_idx ON event (level) WHERE level <> 'info';

-- ---------------------------------------------------------------- views
CREATE OR REPLACE VIEW progress AS
SELECT status, count(*) AS stories
FROM story GROUP BY status ORDER BY 2 DESC;

CREATE OR REPLACE VIEW asset_progress AS
SELECT status, count(*) AS assets, sum(bytes) AS total_bytes
FROM asset GROUP BY status ORDER BY 2 DESC;

CREATE OR REPLACE VIEW sample_status AS
SELECT sharepoint_id, status, upload_full_slug,
       cardinality(scenarios) AS n_scenarios, error
FROM story WHERE is_sample ORDER BY sharepoint_id;

-- Internal links still needing a rewrite, with the story they point at once
-- that story has been uploaded. This is the CSV the link pass exports.
CREATE OR REPLACE VIEW internal_links_todo AS
SELECT l.id, l.sharepoint_id, s.title AS from_title,
       s.sb_story_id AS from_sb_id, s.upload_full_slug AS from_slug,
       l.raw_href, l.link_text,
       l.target_sharepoint_id, t.title AS target_title,
       t.sb_story_id AS target_sb_id, t.sb_uuid AS target_sb_uuid,
       t.upload_full_slug AS target_slug,
       l.resolved, l.resolution_method
FROM link l
JOIN story s ON s.sharepoint_id = l.sharepoint_id
LEFT JOIN story t ON t.sharepoint_id = l.target_sharepoint_id
WHERE l.kind IN ('internal','document')
ORDER BY l.resolved, l.sharepoint_id;

CREATE OR REPLACE VIEW scenario_coverage AS
SELECT unnest(scenarios) AS scenario,
       count(*) AS sample_stories,
       count(*) FILTER (WHERE status = 'uploaded') AS uploaded,
       count(*) FILTER (WHERE status = 'failed')   AS failed
FROM story WHERE is_sample
GROUP BY 1 ORDER BY 1;
