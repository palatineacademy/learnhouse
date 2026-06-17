"""
SQL queries for analytics dashboard — PostgreSQL backend.

Parameters use Python .format() placeholders: {org_id}, {days}, {course_uuid}.
The org_id filter uses the (0 = 0 OR org_id = N) pattern:
  - org_id=0 → returns all orgs
  - org_id=N → filters to org N
"""

# ---------------------------------------------------------------------------
# Core pipes (available to all plans)
# ---------------------------------------------------------------------------

LIVE_USERS = """
SELECT
    org_id,
    COUNT(DISTINCT user_id) AS live_users
FROM analytics_events
WHERE
    ({org_id} = 0 OR org_id = {org_id})
    AND timestamp >= NOW() - INTERVAL '5 minutes'
GROUP BY org_id
"""

DAILY_ACTIVE_USERS = """
SELECT
    org_id,
    timestamp::date AS date,
    COUNT(DISTINCT user_id) AS dau
FROM analytics_events
WHERE
    ({org_id} = 0 OR org_id = {org_id})
    AND timestamp >= NOW() - INTERVAL '{days} days'
GROUP BY org_id, date
ORDER BY date ASC
"""

TOP_COURSES = """
SELECT
    org_id,
    properties->>'course_uuid' AS course_uuid,
    COUNT(DISTINCT CASE WHEN event_name = 'course_view' THEN user_id END) AS views,
    COUNT(DISTINCT CASE WHEN event_name = 'course_enrolled' THEN user_id END) AS enrollments,
    COUNT(DISTINCT CASE WHEN event_name = 'course_completed' THEN user_id END) AS completions
FROM analytics_events
WHERE
    ({org_id} = 0 OR org_id = {org_id})
    AND event_name IN ('course_view', 'course_enrolled', 'course_completed')
    AND timestamp >= NOW() - INTERVAL '{days} days'
GROUP BY org_id, course_uuid
ORDER BY views DESC
LIMIT 20
"""

ENROLLMENT_FUNNEL = """
WITH user_events AS (
    SELECT
        org_id,
        user_id,
        array_agg(DISTINCT event_name) FILTER (WHERE event_name IN ('page_view', 'course_view', 'course_enrolled', 'course_completed')) AS events_set
    FROM analytics_events
    WHERE
        ({org_id} = 0 OR org_id = {org_id})
        AND event_name IN ('page_view', 'course_view', 'course_enrolled', 'course_completed')
        AND timestamp >= NOW() - INTERVAL '{days} days'
    GROUP BY org_id, user_id
)
SELECT
    org_id,
    COUNT(CASE WHEN 'page_view' = ANY(events_set) THEN 1 END) AS page_views,
    COUNT(CASE WHEN 'course_view' = ANY(events_set) THEN 1 END) AS course_views,
    COUNT(CASE WHEN 'course_enrolled' = ANY(events_set) THEN 1 END) AS enrollments,
    COUNT(CASE WHEN 'course_completed' = ANY(events_set) THEN 1 END) AS completions
FROM user_events
GROUP BY org_id
"""

EVENT_COUNTS = """
SELECT
    org_id,
    event_name,
    COUNT(*) AS total,
    COUNT(DISTINCT user_id) AS unique_users
FROM analytics_events
WHERE
    ({org_id} = 0 OR org_id = {org_id})
    AND timestamp >= NOW() - INTERVAL '{days} days'
GROUP BY org_id, event_name
ORDER BY total DESC
"""

VISITORS_BY_COUNTRY = """
SELECT
    org_id,
    properties->>'country_code' AS country_code,
    COUNT(*) AS visits,
    COUNT(DISTINCT user_id) AS unique_users
FROM analytics_events
WHERE
    ({org_id} = 0 OR org_id = {org_id})
    AND event_name = 'page_view'
    AND properties->>'country_code' IS NOT NULL AND properties->>'country_code' != ''
    AND timestamp >= NOW() - INTERVAL '{days} days'
GROUP BY org_id, country_code
ORDER BY visits DESC
LIMIT 20
"""

VISITORS_BY_DEVICE = """
SELECT
    org_id,
    properties->>'device_type' AS device_type,
    COUNT(*) AS visits,
    COUNT(DISTINCT user_id) AS unique_users
FROM analytics_events
WHERE
    ({org_id} = 0 OR org_id = {org_id})
    AND event_name = 'page_view'
    AND properties->>'device_type' IS NOT NULL AND properties->>'device_type' != ''
    AND timestamp >= NOW() - INTERVAL '{days} days'
GROUP BY org_id, device_type
ORDER BY visits DESC
"""

VISITORS_BY_REFERRER = """
SELECT
    org_id,
    properties->>'referrer_domain' AS referrer_domain,
    COUNT(*) AS visits,
    COUNT(DISTINCT user_id) AS unique_users
FROM analytics_events
WHERE
    ({org_id} = 0 OR org_id = {org_id})
    AND event_name = 'page_view'
    AND properties->>'referrer_domain' IS NOT NULL AND properties->>'referrer_domain' != ''
    AND timestamp >= NOW() - INTERVAL '{days} days'
GROUP BY org_id, referrer_domain
ORDER BY visits DESC
LIMIT 20
"""

DAILY_VISITOR_BREAKDOWN = """
SELECT
    org_id,
    timestamp::date AS date,
    COUNT(DISTINCT user_id) AS dau,
    COUNT(CASE WHEN properties->>'device_type' = 'desktop' THEN 1 END) AS desktop,
    COUNT(CASE WHEN properties->>'device_type' = 'mobile' THEN 1 END) AS mobile,
    COUNT(CASE WHEN properties->>'device_type' = 'tablet' THEN 1 END) AS tablet
FROM analytics_events
WHERE
    ({org_id} = 0 OR org_id = {org_id})
    AND event_name = 'page_view'
    AND timestamp >= NOW() - INTERVAL '{days} days'
GROUP BY org_id, date
ORDER BY date ASC
"""

ACTIVITY_ENGAGEMENT = """
SELECT
    org_id,
    properties->>'activity_uuid' AS activity_uuid,
    MAX(CASE WHEN properties->>'activity_type' IS NOT NULL AND properties->>'activity_type' != '' THEN properties->>'activity_type' END) AS activity_type,
    MAX(CASE WHEN properties->>'course_uuid' IS NOT NULL AND properties->>'course_uuid' != '' THEN properties->>'course_uuid' END) AS course_uuid,
    COUNT(DISTINCT CASE WHEN event_name = 'activity_view' THEN user_id END) AS views,
    COUNT(DISTINCT CASE WHEN event_name = 'activity_completed' THEN user_id END) AS completions,
    CASE WHEN COUNT(CASE WHEN event_name = 'time_on_activity' AND (properties->>'seconds_spent')::float > 0 THEN 1 END) > 0
        THEN AVG(CASE WHEN event_name = 'time_on_activity'
                      AND (properties->>'seconds_spent')::float > 0
                      AND (properties->>'seconds_spent')::float <= 14400
                 THEN (properties->>'seconds_spent')::float END)
        ELSE 0
    END AS avg_seconds_spent
FROM analytics_events
WHERE
    ({org_id} = 0 OR org_id = {org_id})
    AND event_name IN ('activity_view', 'activity_completed', 'time_on_activity')
    AND timestamp >= NOW() - INTERVAL '{days} days'
GROUP BY org_id, activity_uuid
ORDER BY views DESC
LIMIT 50
"""

# ---------------------------------------------------------------------------
# Advanced pipes (Pro+ plans only)
# ---------------------------------------------------------------------------

COURSE_DROPOFF = """
WITH enrolled AS (
    SELECT DISTINCT org_id, user_id, properties->>'course_uuid' AS course_uuid
    FROM analytics_events
    WHERE ({org_id} = 0 OR org_id = {org_id}) AND event_name = 'course_enrolled'
        AND timestamp >= NOW() - INTERVAL '{days} days'
),
completed AS (
    SELECT DISTINCT org_id, user_id, properties->>'course_uuid' AS course_uuid
    FROM analytics_events
    WHERE ({org_id} = 0 OR org_id = {org_id}) AND event_name = 'course_completed'
        AND timestamp >= NOW() - INTERVAL '{days} days'
),
last_activity AS (
    SELECT
        org_id,
        user_id,
        properties->>'course_uuid' AS course_uuid,
        (array_agg(properties->>'activity_uuid' ORDER BY timestamp DESC))[1] AS last_activity_uuid
    FROM analytics_events
    WHERE ({org_id} = 0 OR org_id = {org_id}) AND event_name = 'activity_completed'
        AND timestamp >= NOW() - INTERVAL '{days} days'
    GROUP BY org_id, user_id, properties->>'course_uuid'
)
SELECT
    la.org_id,
    la.course_uuid,
    la.last_activity_uuid,
    COUNT(*) AS dropoff_count
FROM enrolled e
LEFT JOIN completed c ON e.user_id = c.user_id AND e.course_uuid = c.course_uuid AND e.org_id = c.org_id
INNER JOIN last_activity la ON e.user_id = la.user_id AND e.course_uuid = la.course_uuid AND e.org_id = la.org_id
WHERE c.user_id IS NULL
GROUP BY la.org_id, la.course_uuid, la.last_activity_uuid
ORDER BY dropoff_count DESC
"""

COHORT_RETENTION = """
WITH signups AS (
    SELECT
        org_id,
        user_id,
        date_trunc('week', timestamp)::date AS cohort_week
    FROM analytics_events
    WHERE ({org_id} = 0 OR org_id = {org_id}) AND event_name = 'user_signed_up'
        AND timestamp >= NOW() - INTERVAL '{days} days'
),
activity AS (
    SELECT DISTINCT
        org_id,
        user_id,
        date_trunc('week', timestamp)::date AS active_week
    FROM analytics_events
    WHERE ({org_id} = 0 OR org_id = {org_id})
        AND timestamp >= NOW() - INTERVAL '{days} days'
)
SELECT
    s.org_id,
    s.cohort_week,
    COUNT(DISTINCT s.user_id) AS cohort_size,
    COUNT(DISTINCT CASE WHEN (a.active_week - s.cohort_week) / 7 = 1 THEN s.user_id END) AS week_1,
    COUNT(DISTINCT CASE WHEN (a.active_week - s.cohort_week) / 7 = 2 THEN s.user_id END) AS week_2,
    COUNT(DISTINCT CASE WHEN (a.active_week - s.cohort_week) / 7 = 4 THEN s.user_id END) AS week_4,
    COUNT(DISTINCT CASE WHEN (a.active_week - s.cohort_week) / 7 = 8 THEN s.user_id END) AS week_8
FROM signups s
LEFT JOIN activity a ON s.user_id = a.user_id AND s.org_id = a.org_id
    AND a.active_week >= s.cohort_week
GROUP BY s.org_id, s.cohort_week
ORDER BY s.cohort_week ASC
"""

TIME_TO_COMPLETION = """
WITH enrollments AS (
    SELECT
        org_id,
        user_id,
        properties->>'course_uuid' AS course_uuid,
        MIN(timestamp) AS enrolled_at
    FROM analytics_events
    WHERE ({org_id} = 0 OR org_id = {org_id}) AND event_name = 'course_enrolled'
        AND timestamp >= NOW() - INTERVAL '{days} days'
    GROUP BY org_id, user_id, properties->>'course_uuid'
),
completions AS (
    SELECT
        org_id,
        user_id,
        properties->>'course_uuid' AS course_uuid,
        MIN(timestamp) AS completed_at
    FROM analytics_events
    WHERE ({org_id} = 0 OR org_id = {org_id}) AND event_name = 'course_completed'
        AND timestamp >= NOW() - INTERVAL '{days} days'
    GROUP BY org_id, user_id, properties->>'course_uuid'
)
SELECT
    e.org_id,
    e.course_uuid,
    PERCENTILE_CONT(0.5) WITHIN GROUP (ORDER BY (c.completed_at::date - e.enrolled_at::date)) AS median_days,
    COUNT(*) AS completions_count
FROM enrollments e
INNER JOIN completions c ON e.user_id = c.user_id AND e.course_uuid = c.course_uuid AND e.org_id = c.org_id
WHERE c.completed_at >= e.enrolled_at
GROUP BY e.org_id, e.course_uuid
ORDER BY median_days ASC
"""

PEAK_USAGE_HOURS = """
SELECT
    org_id,
    EXTRACT(DOW FROM timestamp)::int AS day_of_week,
    EXTRACT(HOUR FROM timestamp)::int AS hour_of_day,
    COUNT(*) AS event_count
FROM analytics_events
WHERE
    ({org_id} = 0 OR org_id = {org_id})
    AND timestamp >= NOW() - INTERVAL '{days} days'
GROUP BY org_id, day_of_week, hour_of_day
ORDER BY day_of_week, hour_of_day
"""

CONTENT_TYPE_EFFECTIVENESS = """
WITH views AS (
    SELECT
        org_id,
        properties->>'activity_type' AS activity_type,
        COUNT(DISTINCT user_id) AS view_count
    FROM analytics_events
    WHERE ({org_id} = 0 OR org_id = {org_id}) AND event_name = 'activity_view'
        AND timestamp >= NOW() - INTERVAL '{days} days'
    GROUP BY org_id, activity_type
),
completions AS (
    SELECT
        org_id,
        properties->>'activity_type' AS activity_type,
        COUNT(DISTINCT user_id) AS completion_count
    FROM analytics_events
    WHERE ({org_id} = 0 OR org_id = {org_id}) AND event_name = 'activity_completed'
        AND timestamp >= NOW() - INTERVAL '{days} days'
    GROUP BY org_id, activity_type
)
SELECT
    v.org_id,
    v.activity_type,
    v.view_count,
    COALESCE(c.completion_count, 0) AS completion_count,
    CASE WHEN v.view_count > 0
        THEN ROUND(COALESCE(c.completion_count, 0)::numeric / v.view_count * 100, 1)
        ELSE 0
    END AS completion_rate
FROM views v
LEFT JOIN completions c ON v.activity_type = c.activity_type AND v.org_id = c.org_id
ORDER BY completion_rate DESC
"""

NEW_VS_RETURNING = """
WITH daily_users AS (
    SELECT DISTINCT org_id, user_id, timestamp::date AS date
    FROM analytics_events
    WHERE ({org_id} = 0 OR org_id = {org_id})
        AND timestamp >= NOW() - INTERVAL '{days} days'
),
first_seen_in_window AS (
    SELECT org_id, user_id, MIN(date) AS first_date
    FROM daily_users
    GROUP BY org_id, user_id
),
ever_seen_before AS (
    SELECT DISTINCT org_id, user_id
    FROM analytics_events
    WHERE ({org_id} = 0 OR org_id = {org_id})
        AND timestamp < NOW() - INTERVAL '{days} days'
)
SELECT
    d.org_id,
    d.date,
    COUNT(CASE WHEN d.date = f.first_date AND e.user_id IS NULL THEN 1 END) AS new_users,
    COUNT(CASE WHEN d.date > f.first_date OR e.user_id IS NOT NULL THEN 1 END) AS returning_users
FROM daily_users d
INNER JOIN first_seen_in_window f ON d.user_id = f.user_id AND d.org_id = f.org_id
LEFT JOIN ever_seen_before e ON d.user_id = e.user_id AND d.org_id = e.org_id
GROUP BY d.org_id, d.date
ORDER BY d.date ASC
"""

COMPLETION_VELOCITY = """
WITH ordered AS (
    SELECT
        org_id,
        user_id,
        properties->>'course_uuid' AS course_uuid,
        timestamp,
        LAG(timestamp) OVER (
            PARTITION BY org_id, user_id, properties->>'course_uuid'
            ORDER BY timestamp
        ) AS prev_ts
    FROM analytics_events
    WHERE ({org_id} = 0 OR org_id = {org_id}) AND event_name = 'activity_completed'
        AND timestamp >= NOW() - INTERVAL '{days} days'
)
SELECT
    org_id,
    course_uuid,
    CASE WHEN COUNT(*) > 0
        THEN ROUND(AVG(EXTRACT(EPOCH FROM (timestamp - prev_ts)) / 3600)::numeric, 1)
        ELSE 0
    END AS avg_hours_between,
    COUNT(*) AS transitions
FROM ordered
WHERE prev_ts IS NOT NULL
    AND prev_ts > '2020-01-01 00:00:00'::timestamp
    AND EXTRACT(EPOCH FROM (timestamp - prev_ts)) / 3600 > 0
GROUP BY org_id, course_uuid
ORDER BY avg_hours_between ASC
"""

COMMUNITY_CORRELATION = """
WITH discussors AS (
    SELECT DISTINCT org_id, user_id
    FROM analytics_events
    WHERE ({org_id} = 0 OR org_id = {org_id}) AND event_name = 'discussion_posted'
        AND timestamp >= NOW() - INTERVAL '{days} days'
),
enrolled AS (
    SELECT DISTINCT org_id, user_id
    FROM analytics_events
    WHERE ({org_id} = 0 OR org_id = {org_id}) AND event_name = 'course_enrolled'
        AND timestamp >= NOW() - INTERVAL '{days} days'
),
completed AS (
    SELECT DISTINCT org_id, user_id
    FROM analytics_events
    WHERE ({org_id} = 0 OR org_id = {org_id}) AND event_name = 'course_completed'
        AND timestamp >= NOW() - INTERVAL '{days} days'
)
SELECT
    e.org_id,
    'discussors' AS group_name,
    COUNT(DISTINCT e.user_id) AS enrolled_count,
    COUNT(DISTINCT c.user_id) AS completed_count,
    CASE WHEN COUNT(DISTINCT e.user_id) > 0
        THEN ROUND(COUNT(DISTINCT c.user_id)::numeric / COUNT(DISTINCT e.user_id) * 100, 1)
        ELSE 0
    END AS completion_rate
FROM enrolled e
INNER JOIN discussors d ON e.user_id = d.user_id AND e.org_id = d.org_id
LEFT JOIN completed c ON e.user_id = c.user_id AND e.org_id = c.org_id
GROUP BY e.org_id
UNION ALL
SELECT
    e.org_id,
    'non_discussors' AS group_name,
    COUNT(DISTINCT e.user_id) AS enrolled_count,
    COUNT(DISTINCT c.user_id) AS completed_count,
    CASE WHEN COUNT(DISTINCT e.user_id) > 0
        THEN ROUND(COUNT(DISTINCT c.user_id)::numeric / COUNT(DISTINCT e.user_id) * 100, 1)
        ELSE 0
    END AS completion_rate
FROM enrolled e
LEFT JOIN discussors d ON e.user_id = d.user_id AND e.org_id = d.org_id
LEFT JOIN completed c ON e.user_id = c.user_id AND e.org_id = c.org_id
WHERE d.user_id IS NULL
GROUP BY e.org_id
"""

USER_PROGRESS_SNAPSHOT = """
WITH total_activities AS (
    SELECT
        org_id,
        properties->>'course_uuid' AS course_uuid,
        COUNT(DISTINCT properties->>'activity_uuid') AS total_count
    FROM analytics_events
    WHERE ({org_id} = 0 OR org_id = {org_id})
        AND event_name IN ('activity_view', 'activity_completed')
        AND properties->>'activity_uuid' IS NOT NULL AND properties->>'activity_uuid' != ''
        AND timestamp >= NOW() - INTERVAL '{days} days'
    GROUP BY org_id, properties->>'course_uuid'
),
user_activities AS (
    SELECT
        org_id,
        user_id,
        properties->>'course_uuid' AS course_uuid,
        COUNT(DISTINCT CASE WHEN event_name = 'activity_completed' THEN properties->>'activity_uuid' END) AS completed_activities
    FROM analytics_events
    WHERE ({org_id} = 0 OR org_id = {org_id})
        AND event_name IN ('course_enrolled', 'activity_completed')
        AND timestamp >= NOW() - INTERVAL '{days} days'
    GROUP BY org_id, user_id, properties->>'course_uuid'
)
SELECT
    ua.org_id,
    ua.course_uuid,
    CASE
        WHEN ta.total_count IS NULL OR ta.total_count = 0 THEN '0%'
        WHEN ua.completed_activities = 0 THEN '0%'
        WHEN (ua.completed_activities::float / ta.total_count) <= 0.25 THEN '1-25%'
        WHEN (ua.completed_activities::float / ta.total_count) <= 0.50 THEN '26-50%'
        WHEN (ua.completed_activities::float / ta.total_count) <= 0.75 THEN '51-75%'
        ELSE '76-100%'
    END AS bracket,
    COUNT(*) AS user_count
FROM user_activities ua
LEFT JOIN total_activities ta ON ua.course_uuid = ta.course_uuid AND ua.org_id = ta.org_id
GROUP BY ua.org_id, ua.course_uuid, bracket
ORDER BY ua.course_uuid, bracket
"""

SEARCH_EFFECTIVENESS = """
SELECT
    org_id,
    properties->>'query' AS query,
    COUNT(*) AS search_count,
    COUNT(CASE WHEN properties->>'results_count' = '0' THEN 1 END) AS zero_results,
    CASE WHEN COUNT(*) > 0
        THEN ROUND(COUNT(CASE WHEN properties->>'results_count' = '0' THEN 1 END)::numeric / COUNT(*) * 100, 1)
        ELSE 0
    END AS zero_result_rate
FROM analytics_events
WHERE
    ({org_id} = 0 OR org_id = {org_id})
    AND event_name = 'search_query'
    AND timestamp >= NOW() - INTERVAL '{days} days'
GROUP BY org_id, query
ORDER BY search_count DESC
LIMIT 50
"""

CERTIFICATION_RATE = """
WITH completers AS (
    SELECT
        org_id,
        properties->>'course_uuid' AS course_uuid,
        COUNT(DISTINCT user_id) AS completions
    FROM analytics_events
    WHERE ({org_id} = 0 OR org_id = {org_id}) AND event_name = 'course_completed'
        AND timestamp >= NOW() - INTERVAL '{days} days'
    GROUP BY org_id, properties->>'course_uuid'
),
cert_claims AS (
    SELECT
        org_id,
        properties->>'course_uuid' AS course_uuid,
        COUNT(DISTINCT user_id) AS claims
    FROM analytics_events
    WHERE ({org_id} = 0 OR org_id = {org_id}) AND event_name = 'certificate_claimed'
        AND timestamp >= NOW() - INTERVAL '{days} days'
    GROUP BY org_id, properties->>'course_uuid'
)
SELECT
    c.org_id,
    c.course_uuid,
    c.completions,
    COALESCE(cc.claims, 0) AS claims,
    CASE WHEN c.completions > 0
        THEN ROUND(COALESCE(cc.claims, 0)::numeric / c.completions * 100, 1)
        ELSE 0
    END AS claim_rate
FROM completers c
LEFT JOIN cert_claims cc ON c.course_uuid = cc.course_uuid AND c.org_id = cc.org_id
ORDER BY c.completions DESC
"""

ORG_GROWTH_TREND = """
SELECT
    org_id,
    date_trunc('week', timestamp) AS week,
    COUNT(DISTINCT CASE WHEN event_name = 'user_signed_up' THEN user_id END) AS signups,
    COUNT(DISTINCT CASE WHEN event_name = 'course_enrolled' THEN user_id END) AS enrollments,
    COUNT(DISTINCT CASE WHEN event_name = 'course_completed' THEN user_id END) AS completions
FROM analytics_events
WHERE
    ({org_id} = 0 OR org_id = {org_id})
    AND timestamp >= NOW() - INTERVAL '{days} days'
    AND event_name IN ('user_signed_up', 'course_enrolled', 'course_completed')
GROUP BY org_id, week
ORDER BY week ASC
"""

LEARNER_ENGAGEMENT_SCORE = """
SELECT
    org_id,
    user_id,
    COUNT(DISTINCT CASE WHEN event_name = 'page_view' THEN properties->>'path' END) AS page_views,
    COUNT(DISTINCT CASE WHEN event_name = 'activity_completed' THEN properties->>'activity_uuid' END) AS activities_completed,
    COUNT(DISTINCT CASE WHEN event_name = 'course_completed' THEN properties->>'course_uuid' END) AS courses_completed,
    COALESCE(SUM(CASE WHEN event_name = 'time_on_activity' AND (properties->>'seconds_spent')::float > 0
                 THEN LEAST((properties->>'seconds_spent')::float, 14400) END), 0) AS total_time_spent,
    LEAST(
        (
            LEAST(COUNT(DISTINCT CASE WHEN event_name = 'page_view' THEN properties->>'path' END), 50) * 1
            + LEAST(COUNT(DISTINCT CASE WHEN event_name = 'activity_completed' THEN properties->>'activity_uuid' END), 100) * 10
            + LEAST(COUNT(DISTINCT CASE WHEN event_name = 'course_completed' THEN properties->>'course_uuid' END), 20) * 50
            + LEAST(COALESCE(SUM(CASE WHEN event_name = 'time_on_activity' AND (properties->>'seconds_spent')::float > 0
                                 THEN LEAST((properties->>'seconds_spent')::float, 14400) END), 0) / 3600, 100) * 5
        ),
        2500
    ) AS engagement_score
FROM analytics_events
WHERE
    ({org_id} = 0 OR org_id = {org_id})
    AND timestamp >= NOW() - INTERVAL '{days} days'
    AND user_id != 0
GROUP BY org_id, user_id
ORDER BY engagement_score DESC
LIMIT 100
"""

COURSE_RATING_BY_COMPLETION = """
WITH course_stats AS (
    SELECT
        org_id,
        properties->>'course_uuid' AS course_uuid,
        COUNT(DISTINCT CASE WHEN event_name = 'course_enrolled' THEN user_id END) AS enrollments,
        COUNT(DISTINCT CASE WHEN event_name = 'course_completed' THEN user_id END) AS completions,
        COUNT(DISTINCT CASE WHEN event_name = 'activity_view' THEN properties->>'activity_uuid' END) AS activity_count
    FROM analytics_events
    WHERE ({org_id} = 0 OR org_id = {org_id})
        AND event_name IN ('course_enrolled', 'course_completed', 'activity_view')
        AND timestamp >= NOW() - INTERVAL '{days} days'
    GROUP BY org_id, properties->>'course_uuid'
)
SELECT
    org_id,
    course_uuid,
    enrollments,
    completions,
    activity_count,
    CASE WHEN enrollments > 0
        THEN ROUND(completions::numeric / enrollments * 100, 1)
        ELSE 0
    END AS completion_rate
FROM course_stats
WHERE enrollments >= 5
ORDER BY enrollments DESC
"""

# ---------------------------------------------------------------------------
# Detail queries (stat-card drill-down)
# ---------------------------------------------------------------------------

DETAIL_LIVE_USERS = """
SELECT
    user_id,
    (array_agg(properties->>'path' ORDER BY timestamp DESC))[1] AS path,
    (array_agg(properties->>'device_type' ORDER BY timestamp DESC))[1] AS device_type,
    (array_agg(properties->>'country_code' ORDER BY timestamp DESC))[1] AS country_code,
    MAX(timestamp) AS last_seen
FROM analytics_events
WHERE
    ({org_id} = 0 OR org_id = {org_id})
    AND event_name = 'page_view'
    AND timestamp >= NOW() - INTERVAL '5 minutes'
    AND user_id != 0
GROUP BY user_id
ORDER BY last_seen DESC
LIMIT 200
"""

DETAIL_SIGNUPS = """
SELECT
    user_id,
    properties->>'signup_method' AS signup_method,
    timestamp
FROM analytics_events
WHERE
    ({org_id} = 0 OR org_id = {org_id})
    AND event_name = 'user_signed_up'
    AND timestamp >= NOW() - INTERVAL '{days} days'
    AND user_id != 0
ORDER BY timestamp DESC
LIMIT 200
"""

DETAIL_ENROLLMENTS = """
SELECT
    user_id,
    properties->>'course_uuid' AS course_uuid,
    MIN(timestamp) AS enrolled_at
FROM analytics_events
WHERE
    ({org_id} = 0 OR org_id = {org_id})
    AND event_name = 'course_enrolled'
    AND timestamp >= NOW() - INTERVAL '{days} days'
    AND user_id != 0
GROUP BY user_id, properties->>'course_uuid'
ORDER BY enrolled_at DESC
LIMIT 200
"""

DETAIL_COMPLETIONS = """
SELECT
    user_id,
    properties->>'course_uuid' AS course_uuid,
    timestamp
FROM analytics_events
WHERE
    ({org_id} = 0 OR org_id = {org_id})
    AND event_name = 'course_completed'
    AND timestamp >= NOW() - INTERVAL '{days} days'
    AND user_id != 0
ORDER BY timestamp DESC
LIMIT 200
"""

DETAIL_QUERIES: dict[str, tuple[str, int]] = {
    "detail_live_users": (DETAIL_LIVE_USERS, 0),
    "detail_signups": (DETAIL_SIGNUPS, 30),
    "detail_enrollments": (DETAIL_ENROLLMENTS, 30),
    "detail_completions": (DETAIL_COMPLETIONS, 30),
    "learner_engagement_score": (LEARNER_ENGAGEMENT_SCORE, 30),
}

# ---------------------------------------------------------------------------
# Registry
# ---------------------------------------------------------------------------

CORE_QUERIES: dict[str, tuple[str, int]] = {
    "live_users": (LIVE_USERS, 0),
    "daily_active_users": (DAILY_ACTIVE_USERS, 30),
    "top_courses": (TOP_COURSES, 30),
    "enrollment_funnel": (ENROLLMENT_FUNNEL, 30),
    "event_counts": (EVENT_COUNTS, 30),
    "activity_engagement": (ACTIVITY_ENGAGEMENT, 30),
    "visitors_by_country": (VISITORS_BY_COUNTRY, 30),
    "visitors_by_device": (VISITORS_BY_DEVICE, 30),
    "visitors_by_referrer": (VISITORS_BY_REFERRER, 30),
    "daily_visitor_breakdown": (DAILY_VISITOR_BREAKDOWN, 30),
}

ADVANCED_QUERIES: dict[str, tuple[str, int]] = {
    "course_dropoff": (COURSE_DROPOFF, 90),
    "cohort_retention": (COHORT_RETENTION, 90),
    "time_to_completion": (TIME_TO_COMPLETION, 180),
    "peak_usage_hours": (PEAK_USAGE_HOURS, 30),
    "content_type_effectiveness": (CONTENT_TYPE_EFFECTIVENESS, 30),
    "new_vs_returning": (NEW_VS_RETURNING, 30),
    "completion_velocity": (COMPLETION_VELOCITY, 90),
    "community_correlation": (COMMUNITY_CORRELATION, 90),
    "user_progress_snapshot": (USER_PROGRESS_SNAPSHOT, 90),
    "search_effectiveness": (SEARCH_EFFECTIVENESS, 30),
    "certification_rate": (CERTIFICATION_RATE, 90),
    "org_growth_trend": (ORG_GROWTH_TREND, 90),
    "course_rating_by_completion": (COURSE_RATING_BY_COMPLETION, 90),
}

# ---------------------------------------------------------------------------
# Course-level queries
# ---------------------------------------------------------------------------

COURSE_OVERVIEW_STATS = """
SELECT
    COUNT(DISTINCT CASE WHEN event_name = 'course_view' THEN user_id END) AS views,
    COUNT(DISTINCT CASE WHEN event_name = 'course_enrolled' THEN user_id END) AS enrollments,
    COUNT(DISTINCT CASE WHEN event_name = 'course_completed' THEN user_id END) AS completions,
    CASE WHEN COUNT(DISTINCT CASE WHEN event_name = 'course_enrolled' THEN user_id END) > 0
        THEN ROUND(
            COUNT(DISTINCT CASE WHEN event_name = 'course_completed' THEN user_id END)::numeric /
            COUNT(DISTINCT CASE WHEN event_name = 'course_enrolled' THEN user_id END) * 100, 1)
        ELSE 0
    END AS completion_rate
FROM analytics_events
WHERE
    ({org_id} = 0 OR org_id = {org_id})
    AND properties->>'course_uuid' = '{course_uuid}'
    AND event_name IN ('course_view', 'course_enrolled', 'course_completed')
    AND timestamp >= NOW() - INTERVAL '{days} days'
"""

COURSE_ENROLLMENT_TREND = """
SELECT
    timestamp::date AS date,
    COUNT(DISTINCT user_id) AS enrollments
FROM analytics_events
WHERE
    ({org_id} = 0 OR org_id = {org_id})
    AND properties->>'course_uuid' = '{course_uuid}'
    AND event_name = 'course_enrolled'
    AND timestamp >= NOW() - INTERVAL '{days} days'
GROUP BY date
ORDER BY date ASC
"""

COURSE_ACTIVITY_FUNNEL = """
SELECT
    properties->>'activity_uuid' AS activity_uuid,
    COUNT(DISTINCT CASE WHEN event_name = 'activity_view' THEN user_id END) AS views,
    COUNT(DISTINCT CASE WHEN event_name = 'activity_completed' THEN user_id END) AS completions,
    CASE WHEN COUNT(DISTINCT CASE WHEN event_name = 'activity_view' THEN user_id END) > 0
        THEN ROUND(
            COUNT(DISTINCT CASE WHEN event_name = 'activity_completed' THEN user_id END)::numeric /
            COUNT(DISTINCT CASE WHEN event_name = 'activity_view' THEN user_id END) * 100, 1)
        ELSE 0
    END AS completion_rate
FROM analytics_events
WHERE
    ({org_id} = 0 OR org_id = {org_id})
    AND properties->>'course_uuid' = '{course_uuid}'
    AND event_name IN ('activity_view', 'activity_completed')
    AND timestamp >= NOW() - INTERVAL '{days} days'
GROUP BY activity_uuid
ORDER BY views DESC
"""

COURSE_LEARNER_PROGRESS = """
WITH user_completions AS (
    SELECT
        user_id,
        COUNT(DISTINCT properties->>'activity_uuid') AS completed_activities
    FROM analytics_events
    WHERE
        ({org_id} = 0 OR org_id = {org_id})
        AND properties->>'course_uuid' = '{course_uuid}'
        AND event_name = 'activity_completed'
        AND timestamp >= NOW() - INTERVAL '{days} days'
    GROUP BY user_id
)
SELECT
    CASE
        WHEN completed_activities = 0 THEN '0'
        WHEN completed_activities <= 2 THEN '1-2'
        WHEN completed_activities <= 5 THEN '3-5'
        WHEN completed_activities <= 10 THEN '6-10'
        ELSE '11+'
    END AS bracket,
    COUNT(*) AS user_count
FROM user_completions
GROUP BY bracket
ORDER BY bracket
"""

COURSE_TIME_PER_ACTIVITY = """
SELECT
    properties->>'activity_uuid' AS activity_uuid,
    CASE WHEN COUNT(*) > 0
        THEN ROUND(AVG(LEAST((properties->>'seconds_spent')::float, 14400))::numeric, 1)
        ELSE 0
    END AS avg_seconds_spent,
    COUNT(*) AS samples
FROM analytics_events
WHERE
    ({org_id} = 0 OR org_id = {org_id})
    AND properties->>'course_uuid' = '{course_uuid}'
    AND event_name = 'time_on_activity'
    AND (properties->>'seconds_spent')::float > 0
    AND timestamp >= NOW() - INTERVAL '{days} days'
GROUP BY activity_uuid
ORDER BY avg_seconds_spent DESC
"""

COURSE_COMPLETION_VELOCITY = """
WITH ordered AS (
    SELECT
        user_id,
        timestamp,
        LAG(timestamp) OVER (
            PARTITION BY user_id
            ORDER BY timestamp
        ) AS prev_ts
    FROM analytics_events
    WHERE
        ({org_id} = 0 OR org_id = {org_id})
        AND properties->>'course_uuid' = '{course_uuid}'
        AND event_name = 'activity_completed'
        AND timestamp >= NOW() - INTERVAL '{days} days'
)
SELECT
    CASE WHEN COUNT(*) > 0
        THEN ROUND(AVG(EXTRACT(EPOCH FROM (timestamp - prev_ts)) / 3600)::numeric, 1)
        ELSE 0
    END AS avg_hours_between,
    COUNT(*) AS transitions
FROM ordered
WHERE prev_ts IS NOT NULL
    AND prev_ts > '2020-01-01 00:00:00'::timestamp
    AND EXTRACT(EPOCH FROM (timestamp - prev_ts)) / 3600 > 0
"""

COURSE_ACTIVE_LEARNERS = """
SELECT
    timestamp::date AS date,
    COUNT(DISTINCT user_id) AS active_learners
FROM analytics_events
WHERE
    ({org_id} = 0 OR org_id = {org_id})
    AND properties->>'course_uuid' = '{course_uuid}'
    AND timestamp >= NOW() - INTERVAL '{days} days'
GROUP BY date
ORDER BY date ASC
"""

COURSE_TIME_TO_COMPLETION = """
WITH enrollments AS (
    SELECT
        user_id,
        MIN(timestamp) AS enrolled_at
    FROM analytics_events
    WHERE
        ({org_id} = 0 OR org_id = {org_id})
        AND properties->>'course_uuid' = '{course_uuid}'
        AND event_name = 'course_enrolled'
        AND timestamp >= NOW() - INTERVAL '{days} days'
    GROUP BY user_id
),
completions AS (
    SELECT
        user_id,
        MIN(timestamp) AS completed_at
    FROM analytics_events
    WHERE
        ({org_id} = 0 OR org_id = {org_id})
        AND properties->>'course_uuid' = '{course_uuid}'
        AND event_name = 'course_completed'
        AND timestamp >= NOW() - INTERVAL '{days} days'
    GROUP BY user_id
)
SELECT
    PERCENTILE_CONT(0.5) WITHIN GROUP (ORDER BY (c.completed_at::date - e.enrolled_at::date)) AS median_days,
    COUNT(*) AS completions_count,
    PERCENTILE_CONT(0.25) WITHIN GROUP (ORDER BY (c.completed_at::date - e.enrolled_at::date)) AS p25_days,
    PERCENTILE_CONT(0.75) WITHIN GROUP (ORDER BY (c.completed_at::date - e.enrolled_at::date)) AS p75_days
FROM enrollments e
INNER JOIN completions c ON e.user_id = c.user_id
WHERE c.completed_at >= e.enrolled_at
"""

COURSE_CERTIFICATION_RATE = """
WITH completers AS (
    SELECT COUNT(DISTINCT user_id) AS completions
    FROM analytics_events
    WHERE
        ({org_id} = 0 OR org_id = {org_id})
        AND properties->>'course_uuid' = '{course_uuid}'
        AND event_name = 'course_completed'
        AND timestamp >= NOW() - INTERVAL '{days} days'
),
cert_claims AS (
    SELECT COUNT(DISTINCT user_id) AS claims
    FROM analytics_events
    WHERE
        ({org_id} = 0 OR org_id = {org_id})
        AND properties->>'course_uuid' = '{course_uuid}'
        AND event_name = 'certificate_claimed'
        AND timestamp >= NOW() - INTERVAL '{days} days'
)
SELECT
    completers.completions,
    cert_claims.claims,
    CASE WHEN completers.completions > 0
        THEN ROUND(cert_claims.claims::numeric / completers.completions * 100, 1)
        ELSE 0
    END AS claim_rate
FROM completers, cert_claims
"""

COURSE_VIEW_TO_ENROLLMENT = """
SELECT
    timestamp::date AS date,
    COUNT(DISTINCT CASE WHEN event_name = 'course_view' THEN user_id END) AS views,
    COUNT(DISTINCT CASE WHEN event_name = 'course_enrolled' THEN user_id END) AS enrollments,
    CASE WHEN COUNT(DISTINCT CASE WHEN event_name = 'course_view' THEN user_id END) > 0
        THEN ROUND(
            COUNT(DISTINCT CASE WHEN event_name = 'course_enrolled' THEN user_id END)::numeric /
            COUNT(DISTINCT CASE WHEN event_name = 'course_view' THEN user_id END) * 100, 1)
        ELSE 0
    END AS conversion_rate
FROM analytics_events
WHERE
    ({org_id} = 0 OR org_id = {org_id})
    AND properties->>'course_uuid' = '{course_uuid}'
    AND event_name IN ('course_view', 'course_enrolled')
    AND timestamp >= NOW() - INTERVAL '{days} days'
GROUP BY date
ORDER BY date ASC
"""

COURSE_ACTIVITY_TYPE_BREAKDOWN = """
SELECT
    properties->>'activity_type' AS activity_type,
    COUNT(DISTINCT CASE WHEN event_name = 'activity_view' THEN user_id END) AS views,
    COUNT(DISTINCT CASE WHEN event_name = 'activity_completed' THEN user_id END) AS completions,
    CASE WHEN COUNT(DISTINCT CASE WHEN event_name = 'activity_view' THEN user_id END) > 0
        THEN ROUND(
            COUNT(DISTINCT CASE WHEN event_name = 'activity_completed' THEN user_id END)::numeric /
            COUNT(DISTINCT CASE WHEN event_name = 'activity_view' THEN user_id END) * 100, 1)
        ELSE 0
    END AS completion_rate
FROM analytics_events
WHERE
    ({org_id} = 0 OR org_id = {org_id})
    AND properties->>'course_uuid' = '{course_uuid}'
    AND event_name IN ('activity_view', 'activity_completed')
    AND properties->>'activity_type' IS NOT NULL AND properties->>'activity_type' != ''
    AND timestamp >= NOW() - INTERVAL '{days} days'
GROUP BY activity_type
ORDER BY views DESC
"""

COURSE_PEAK_HOURS = """
SELECT
    EXTRACT(HOUR FROM timestamp)::int AS hour,
    EXTRACT(DOW FROM timestamp)::int AS day_of_week,
    COUNT(*) AS event_count
FROM analytics_events
WHERE
    ({org_id} = 0 OR org_id = {org_id})
    AND properties->>'course_uuid' = '{course_uuid}'
    AND event_name IN ('activity_view', 'activity_completed', 'time_on_activity')
    AND timestamp >= NOW() - INTERVAL '{days} days'
GROUP BY hour, day_of_week
ORDER BY day_of_week, hour
"""

COURSE_LEARNER_RETENTION = """
WITH first_activity AS (
    SELECT
        user_id,
        MIN(timestamp::date) AS first_day
    FROM analytics_events
    WHERE
        ({org_id} = 0 OR org_id = {org_id})
        AND properties->>'course_uuid' = '{course_uuid}'
        AND event_name IN ('activity_view', 'activity_completed')
        AND timestamp >= NOW() - INTERVAL '{days} days'
    GROUP BY user_id
),
daily_activity AS (
    SELECT DISTINCT
        user_id,
        timestamp::date AS active_day
    FROM analytics_events
    WHERE
        ({org_id} = 0 OR org_id = {org_id})
        AND properties->>'course_uuid' = '{course_uuid}'
        AND event_name IN ('activity_view', 'activity_completed')
        AND timestamp >= NOW() - INTERVAL '{days} days'
)
SELECT
    (d.active_day - f.first_day) AS days_since_start,
    COUNT(DISTINCT d.user_id) AS active_users,
    (SELECT COUNT(DISTINCT user_id) FROM first_activity) AS cohort_size
FROM first_activity f
INNER JOIN daily_activity d ON f.user_id = d.user_id
WHERE (d.active_day - f.first_day) >= 0
    AND (d.active_day - f.first_day) <= 30
GROUP BY days_since_start
ORDER BY days_since_start
"""

COURSE_TOP_LEARNERS = """
SELECT
    user_id,
    COUNT(DISTINCT CASE WHEN event_name = 'activity_completed' THEN properties->>'activity_uuid' END) AS completions,
    COUNT(DISTINCT CASE WHEN event_name = 'activity_view' THEN properties->>'activity_uuid' END) AS views,
    COALESCE(SUM(CASE WHEN event_name = 'time_on_activity' AND (properties->>'seconds_spent')::float > 0
                 THEN LEAST((properties->>'seconds_spent')::float, 14400) END), 0) AS total_seconds_spent
FROM analytics_events
WHERE
    ({org_id} = 0 OR org_id = {org_id})
    AND properties->>'course_uuid' = '{course_uuid}'
    AND event_name IN ('activity_completed', 'activity_view', 'time_on_activity')
    AND timestamp >= NOW() - INTERVAL '{days} days'
    AND user_id != 0
GROUP BY user_id
ORDER BY completions DESC, views DESC
LIMIT 20
"""

COURSE_ACTIVITY_DROPOFF = """
WITH user_activities AS (
    SELECT
        user_id,
        properties->>'activity_uuid' AS activity_uuid,
        MIN(timestamp) AS first_completed_at
    FROM analytics_events
    WHERE
        ({org_id} = 0 OR org_id = {org_id})
        AND properties->>'course_uuid' = '{course_uuid}'
        AND event_name = 'activity_completed'
        AND timestamp >= NOW() - INTERVAL '{days} days'
    GROUP BY user_id, properties->>'activity_uuid'
),
user_max_activity AS (
    SELECT
        user_id,
        (array_agg(activity_uuid ORDER BY first_completed_at DESC))[1] AS last_activity_uuid,
        COUNT(*) AS total_completed
    FROM user_activities
    GROUP BY user_id
)
SELECT
    last_activity_uuid AS activity_uuid,
    COUNT(*) AS users_stopped_here,
    CASE WHEN COUNT(*) > 0 THEN AVG(total_completed) ELSE 0 END AS avg_completed_before_stop
FROM user_max_activity
GROUP BY last_activity_uuid
ORDER BY users_stopped_here DESC
LIMIT 20
"""

COURSE_ENGAGEMENT_BY_TYPE = """
SELECT
    properties->>'activity_type' AS activity_type,
    COUNT(DISTINCT user_id) AS unique_learners,
    COUNT(*) AS total_events,
    COUNT(DISTINCT CASE WHEN event_name = 'activity_completed' THEN user_id END) AS completions,
    CASE WHEN COUNT(CASE WHEN event_name = 'time_on_activity' AND (properties->>'seconds_spent')::float > 0 THEN 1 END) > 0
        THEN AVG(CASE WHEN event_name = 'time_on_activity'
                      AND (properties->>'seconds_spent')::float > 0
                      AND (properties->>'seconds_spent')::float <= 14400
                 THEN (properties->>'seconds_spent')::float END)
        ELSE 0
    END AS avg_seconds_spent
FROM analytics_events
WHERE
    ({org_id} = 0 OR org_id = {org_id})
    AND properties->>'course_uuid' = '{course_uuid}'
    AND event_name IN ('activity_view', 'activity_completed', 'time_on_activity')
    AND properties->>'activity_type' IS NOT NULL AND properties->>'activity_type' != ''
    AND timestamp >= NOW() - INTERVAL '{days} days'
GROUP BY activity_type
ORDER BY total_events DESC
"""

COURSE_DAILY_COMPLETIONS = """
SELECT
    timestamp::date AS date,
    COUNT(*) AS completions,
    COUNT(DISTINCT user_id) AS unique_completers
FROM analytics_events
WHERE
    ({org_id} = 0 OR org_id = {org_id})
    AND properties->>'course_uuid' = '{course_uuid}'
    AND event_name = 'activity_completed'
    AND timestamp >= NOW() - INTERVAL '{days} days'
GROUP BY date
ORDER BY date ASC
"""

COURSE_AVG_SESSION_DURATION = """
SELECT
    timestamp::date AS date,
    ROUND(
        SUM(LEAST((properties->>'seconds_spent')::float, 14400)) /
        GREATEST(COUNT(DISTINCT user_id), 1), 0
    ) AS avg_seconds_per_user,
    SUM(LEAST((properties->>'seconds_spent')::float, 14400)) AS total_seconds,
    COUNT(DISTINCT user_id) AS unique_users
FROM analytics_events
WHERE
    ({org_id} = 0 OR org_id = {org_id})
    AND properties->>'course_uuid' = '{course_uuid}'
    AND event_name = 'time_on_activity'
    AND (properties->>'seconds_spent')::float > 0
    AND timestamp >= NOW() - INTERVAL '{days} days'
GROUP BY date
ORDER BY date ASC
"""

COURSE_UNIQUE_VIEWERS = """
SELECT
    timestamp::date AS date,
    COUNT(DISTINCT user_id) AS unique_viewers,
    COUNT(*) AS total_views
FROM analytics_events
WHERE
    ({org_id} = 0 OR org_id = {org_id})
    AND properties->>'course_uuid' = '{course_uuid}'
    AND event_name = 'course_view'
    AND timestamp >= NOW() - INTERVAL '{days} days'
GROUP BY date
ORDER BY date ASC
"""

COURSE_RECENT_ENROLLMENTS = """
SELECT
    user_id,
    MIN(timestamp) AS enrolled_at
FROM analytics_events
WHERE
    ({org_id} = 0 OR org_id = {org_id})
    AND properties->>'course_uuid' = '{course_uuid}'
    AND event_name = 'course_enrolled'
    AND timestamp >= NOW() - INTERVAL '{days} days'
    AND user_id != 0
GROUP BY user_id
ORDER BY enrolled_at DESC
LIMIT 50
"""

COURSE_QUERIES: dict[str, tuple[str, int]] = {
    "course_overview_stats": (COURSE_OVERVIEW_STATS, 30),
    "course_enrollment_trend": (COURSE_ENROLLMENT_TREND, 30),
    "course_activity_funnel": (COURSE_ACTIVITY_FUNNEL, 30),
    "course_learner_progress": (COURSE_LEARNER_PROGRESS, 90),
    "course_time_per_activity": (COURSE_TIME_PER_ACTIVITY, 30),
    "course_completion_velocity": (COURSE_COMPLETION_VELOCITY, 90),
    "course_active_learners": (COURSE_ACTIVE_LEARNERS, 30),
    "course_time_to_completion": (COURSE_TIME_TO_COMPLETION, 180),
    "course_certification_rate": (COURSE_CERTIFICATION_RATE, 90),
    "course_view_to_enrollment": (COURSE_VIEW_TO_ENROLLMENT, 30),
    "course_activity_type_breakdown": (COURSE_ACTIVITY_TYPE_BREAKDOWN, 30),
    "course_peak_hours": (COURSE_PEAK_HOURS, 30),
    "course_learner_retention": (COURSE_LEARNER_RETENTION, 90),
    "course_activity_dropoff": (COURSE_ACTIVITY_DROPOFF, 90),
    "course_engagement_by_type": (COURSE_ENGAGEMENT_BY_TYPE, 30),
    "course_daily_completions": (COURSE_DAILY_COMPLETIONS, 30),
    "course_avg_session_duration": (COURSE_AVG_SESSION_DURATION, 30),
    "course_unique_viewers": (COURSE_UNIQUE_VIEWERS, 30),
}

COURSE_DETAIL_QUERIES: dict[str, tuple[str, int]] = {
    "course_recent_enrollments": (COURSE_RECENT_ENROLLMENTS, 30),
    "course_top_learners": (COURSE_TOP_LEARNERS, 90),
}

ALL_QUERIES = {**CORE_QUERIES, **ADVANCED_QUERIES, **DETAIL_QUERIES}
