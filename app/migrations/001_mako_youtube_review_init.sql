BEGIN;

CREATE TABLE chart_snapshot (
    id BIGSERIAL PRIMARY KEY,
    source_name TEXT NOT NULL,
    source_url TEXT NOT NULL,
    snapshot_date DATE NOT NULL,
    fetched_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    status TEXT NOT NULL,
    raw_payload_json JSONB,
    scraper_version TEXT,
    notes TEXT
);

CREATE TABLE chart_entry (
    id BIGSERIAL PRIMARY KEY,
    snapshot_id BIGINT NOT NULL REFERENCES chart_snapshot(id) ON DELETE CASCADE,
    chart_position INTEGER NOT NULL,
    artist_raw TEXT,
    song_title_raw TEXT,
    artist_norm TEXT,
    song_title_norm TEXT,
    youtube_url TEXT,
    youtube_video_id TEXT,
    has_youtube BOOLEAN NOT NULL DEFAULT FALSE,
    pipeline_status TEXT NOT NULL DEFAULT 'discovered',
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX idx_chart_entry_snapshot_id ON chart_entry(snapshot_id);
CREATE INDEX idx_chart_entry_youtube_video_id ON chart_entry(youtube_video_id);
CREATE INDEX idx_chart_entry_pipeline_status ON chart_entry(pipeline_status);

CREATE TABLE youtube_video (
    id BIGSERIAL PRIMARY KEY,
    youtube_video_id TEXT NOT NULL UNIQUE,
    canonical_url TEXT NOT NULL,
    video_title TEXT,
    channel_title TEXT,
    description_raw TEXT,
    published_at TIMESTAMPTZ,
    metadata_fetched_at TIMESTAMPTZ,
    fetch_status TEXT NOT NULL,
    fetch_error TEXT,
    fetcher_version TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX idx_youtube_video_fetch_status ON youtube_video(fetch_status);

CREATE TABLE review_task (
    id BIGSERIAL PRIMARY KEY,
    chart_entry_id BIGINT NOT NULL REFERENCES chart_entry(id) ON DELETE CASCADE,
    youtube_video_id_ref TEXT NOT NULL REFERENCES youtube_video(youtube_video_id) ON DELETE CASCADE,
    review_status TEXT NOT NULL DEFAULT 'pending',
    assigned_to TEXT,
    priority INTEGER NOT NULL DEFAULT 100,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    started_at TIMESTAMPTZ,
    completed_at TIMESTAMPTZ
);

CREATE INDEX idx_review_task_status ON review_task(review_status);
CREATE INDEX idx_review_task_chart_entry_id ON review_task(chart_entry_id);

CREATE TABLE review_result (
    id BIGSERIAL PRIMARY KEY,
    review_task_id BIGINT NOT NULL UNIQUE REFERENCES review_task(id) ON DELETE CASCADE,
    operator_id TEXT,
    final_artist TEXT,
    final_song_title TEXT,
    final_lyrics_text TEXT,
    decision TEXT NOT NULL,
    review_notes TEXT,
    reviewed_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX idx_review_result_decision ON review_result(decision);

CREATE TABLE audit_event (
    id BIGSERIAL PRIMARY KEY,
    entity_type TEXT NOT NULL,
    entity_id TEXT NOT NULL,
    event_type TEXT NOT NULL,
    event_payload_json JSONB,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    actor_type TEXT,
    actor_id TEXT
);

CREATE INDEX idx_audit_event_entity ON audit_event(entity_type, entity_id);
CREATE INDEX idx_audit_event_event_type ON audit_event(event_type);

COMMIT;
