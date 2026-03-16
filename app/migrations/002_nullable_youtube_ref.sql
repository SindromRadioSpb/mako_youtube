BEGIN;

-- Allow review tasks to exist without a YouTube video reference
-- (entries where the chart has no YouTube link, or where video fetch failed).
ALTER TABLE review_task ALTER COLUMN youtube_video_id_ref DROP NOT NULL;

-- Replace CASCADE delete with SET NULL: deleting a youtube_video row no longer
-- cascade-deletes the review task — it just clears the reference so the task
-- remains available for manual YouTube assignment.
ALTER TABLE review_task
    DROP CONSTRAINT IF EXISTS review_task_youtube_video_id_ref_fkey;

ALTER TABLE review_task
    ADD CONSTRAINT review_task_youtube_video_id_ref_fkey
        FOREIGN KEY (youtube_video_id_ref)
        REFERENCES youtube_video(youtube_video_id)
        ON DELETE SET NULL;

COMMIT;
