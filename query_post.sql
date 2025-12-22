-- Query to find post by ID (or recent posts if not found)
-- First try with the redis_id as post_id
SELECT
    p.id as post_id,
    u.name,
    u.username,
    p.title,
    p.caption,
    p.location,
    p.ai_sentence,
    p.created_at,
    COUNT(DISTINCT l.id) as like_count,
    COUNT(DISTINCT c.id) as comment_count
FROM posts p
JOIN users u ON p.user_id = u.id
LEFT JOIN likes l ON l.post_id = p.id
LEFT JOIN comments c ON c.post_id = p.id
WHERE p.id = 'd28fc897-3d92-4bf2-a6a6-d91a5013e0ab'
GROUP BY p.id, u.name, u.username, p.title, p.caption, p.location, p.ai_sentence, p.created_at;

-- If no results, show most recent posts
SELECT
    p.id as post_id,
    u.name,
    u.username,
    p.title,
    p.caption,
    p.location,
    p.ai_sentence,
    p.created_at,
    COUNT(DISTINCT l.id) as like_count,
    COUNT(DISTINCT c.id) as comment_count
FROM posts p
JOIN users u ON p.user_id = u.id
LEFT JOIN likes l ON l.post_id = p.id
LEFT JOIN comments c ON c.post_id = p.id
GROUP BY p.id, u.name, u.username, p.title, p.caption, p.location, p.ai_sentence, p.created_at
ORDER BY p.created_at DESC
LIMIT 5;

-- Get media for a specific post
SELECT media_url, created_at
FROM post_media
WHERE post_id = 'd28fc897-3d92-4bf2-a6a6-d91a5013e0ab'
ORDER BY created_at;
